// Isolated ordinary KVM RAM; no PCI devices, QEMU, display, network or firmware.
#define _GNU_SOURCE
#include <linux/kvm.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"failed %s errno=%d\n",#x,errno);exit(1);}}while(0)
static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
int main(void){
 alarm(60);setvbuf(stdout,NULL,_IOLBF,0);
 int kvm=open("/dev/kvm",O_RDWR|O_CLOEXEC);CHECK(kvm>=0);
 CHECK(ioctl(kvm,KVM_GET_API_VERSION,0)==12);
 int vm=ioctl(kvm,KVM_CREATE_VM,0);CHECK(vm>=0);
 const size_t codeSize=2*1024*1024,maxSize=3840*2160*4;
 uint8_t *code=mmap(NULL,codeSize,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 uint32_t *data=mmap(NULL,maxSize,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
 CHECK(code!=MAP_FAILED&&data!=MAP_FAILED);memset(code,0,codeSize);memset(data,0,maxSize);
 struct kvm_userspace_memory_region region={.slot=0,.guest_phys_addr=0,.memory_size=codeSize,.userspace_addr=(uintptr_t)code};
 CHECK(ioctl(vm,KVM_SET_USER_MEMORY_REGION,&region)==0);
 // 32-bit flat protected mode: CLD; REP STOSD; HLT. Counts/registers supplied by host.
 code[4096]=0xfc;code[4097]=0xf3;code[4098]=0xab;code[4099]=0xf4;
 int cpu=ioctl(vm,KVM_CREATE_VCPU,0);CHECK(cpu>=0);
 int runSize=ioctl(kvm,KVM_GET_VCPU_MMAP_SIZE,0);CHECK(runSize>0);
 struct kvm_run *run=mmap(NULL,runSize,PROT_READ|PROT_WRITE,MAP_SHARED,cpu,0);CHECK(run!=MAP_FAILED);
 struct kvm_sregs sr;CHECK(ioctl(cpu,KVM_GET_SREGS,&sr)==0);
 struct kvm_segment seg={.base=0,.limit=0xffffffff,.selector=16,.type=3,.present=1,.dpl=0,.db=1,.s=1,.g=1};
 sr.ds=sr.es=sr.fs=sr.gs=sr.ss=seg;seg.selector=8;seg.type=11;sr.cs=seg;sr.cr0=1;sr.cr3=0;sr.cr4=0;sr.efer=0;
 CHECK(ioctl(cpu,KVM_SET_SREGS,&sr)==0);
 printf("IDENTITY pid=%ld api=12 guest=flat32 ordinary_ram=1 manual_dirty_protect=0 data_gpa=%zu\n",(long)getpid(),codeSize);
 // Manual dirty protection is deliberately not enabled: GET_DIRTY_LOG clears/rearms.
 size_t sizes[]={1920*1080*4,3840*2160*4};
 for(unsigned sizeIndex=0;sizeIndex<2;sizeIndex++)for(unsigned pass=0;pass<4;pass++){
  unsigned logging=pass%2;size_t bytes=sizes[sizeIndex],pages=bytes/4096;
  region=(struct kvm_userspace_memory_region){.slot=1,.flags=logging?KVM_MEM_LOG_DIRTY_PAGES:0,.guest_phys_addr=codeSize,.memory_size=bytes,.userspace_addr=(uintptr_t)data};
  CHECK(ioctl(vm,KVM_SET_USER_MEMORY_REGION,&region)==0);
  size_t bitmapBytes=((pages+63)/64)*8;unsigned long *bitmap=calloc(1,bitmapBytes);CHECK(bitmap);
  struct kvm_dirty_log log={.slot=1,.dirty_bitmap=bitmap};
  for(unsigned pair=0;pair<6;pair++){
   if(logging){memset(bitmap,0,bitmapBytes);CHECK(ioctl(vm,KVM_GET_DIRTY_LOG,&log)==0);}
   double duration[2];
   for(unsigned write=0;write<2;write++){
    uint32_t pattern=0x13570000u|(pass<<8)|(pair<<1)|write;
    struct kvm_regs regs={.rip=4096,.rflags=2,.rdi=codeSize,.rcx=bytes/4,.rax=pattern,.rsp=codeSize-16};
    CHECK(ioctl(cpu,KVM_SET_REGS,&regs)==0);
    double start=now();CHECK(ioctl(cpu,KVM_RUN,0)==0);duration[write]=now()-start;
    if(run->exit_reason!=KVM_EXIT_HLT){fprintf(stderr,"unexpected exit=%u\n",run->exit_reason);return 1;}
    // Host readback is outside timing and intentionally identical in every case.
    for(size_t i=0;i<bytes/4;i++)CHECK(data[i]==pattern);
   }
   unsigned dirty=0;
   if(logging){memset(bitmap,0,bitmapBytes);CHECK(ioctl(vm,KVM_GET_DIRTY_LOG,&log)==0);
    for(size_t i=0;i<pages;i++)dirty+=(bitmap[i/(8*sizeof(long))]>>(i%(8*sizeof(long))))&1;
    CHECK(dirty==pages);
   }
   printf("PAIR bytes=%zu logging=%u pass=%u pair=%u first_ms=%.6f second_ms=%.6f verified_words=%zu dirty_pages=%u\n",bytes,logging,pass,pair,1000*duration[0],1000*duration[1],bytes/4,dirty);
  }
  free(bitmap);region.memory_size=0;CHECK(ioctl(vm,KVM_SET_USER_MEMORY_REGION,&region)==0);
 }
 munmap(run,runSize);close(cpu);close(vm);close(kvm);munmap(code,codeSize);munmap(data,maxSize);
 puts("COMPLETE closed_owned_vm=1");return 0;
}
