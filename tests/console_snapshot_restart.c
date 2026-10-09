/* Native restartable snapshot qualification; run only with ordinary presenter stopped.
 * clang -O2 console_snapshot_restart.c -framework IOKit -framework CoreFoundation
 * --hold-seconds N (0..30 total) gives host two full-pixel screenshot windows.
 * Expected801x601 XRGB: B=x%256,G=y%256,R=(x+y)%256; byte3=255.
 * Tests the bridge, not manager delivery. No physical GPU mapping or raw MMIO.
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define BYTES (32ULL*1024*1024)
#define WIDTH 801u
#define HEIGHT 601u
struct owner { io_connect_t connection; mach_vm_address_t address; mach_vm_size_t length; int armed; };
static volatile sig_atomic_t interrupted;
static void interrupt_handler(int sig) { (void)sig; interrupted=1; }
static void fence(void) { __asm__ volatile("sfence" ::: "memory"); }
static int property_one(io_service_t s, CFStringRef key) {
    CFTypeRef p=IORegistryEntryCreateCFProperty(s,key,kCFAllocatorDefault,0);
    int n=0,ok=p && CFGetTypeID(p)==CFNumberGetTypeID() &&
        CFNumberGetValue((CFNumberRef)p,kCFNumberIntType,&n) && n==1;
    if(p)CFRelease(p); return ok;
}
static kern_return_t arm(struct owner *o) {
    kern_return_t r=IOConnectCallScalarMethod(o->connection,1,NULL,0,NULL,NULL);
    if(r==KERN_SUCCESS)o->armed=1; return r;
}
static kern_return_t retire(struct owner *o) {
    kern_return_t r=IOConnectCallScalarMethod(o->connection,3,NULL,0,NULL,NULL);
    if(r==KERN_SUCCESS)o->armed=0; return r;
}
static int cleanup(struct owner *o) {
    int ok=1;
    if(o->armed && retire(o)!=KERN_SUCCESS)ok=0;
    if(o->address) {
        if(IOConnectUnmapMemory64(o->connection,1,mach_task_self(),o->address)!=KERN_SUCCESS)ok=0;
        else o->address=0;
    }
    if(o->connection) {
        if(IOServiceClose(o->connection)!=KERN_SUCCESS)ok=0;
        else o->connection=0;
    }
    return ok;
}
static int zero_buffer(struct owner *o) {
    const volatile uint32_t *p=(void *)(uintptr_t)o->address;
    for(size_t i=0;i<BYTES/4;i++)if(p[i] || interrupted)return 0;
    return 1;
}
static uint32_t pixel(unsigned x,unsigned y) {
    return 0xff000000u|(((x+y)&255u)<<16)|((y&255u)<<8)|(x&255u);
}
static size_t mismatches(struct owner *o) {
    const volatile uint32_t *p=(void *)(uintptr_t)o->address; size_t n=0;
    for(unsigned y=0;y<HEIGHT;y++)for(unsigned x=0;x<WIDTH;x++)n+=p[y*WIDTH+x]!=pixel(x,y);
    return n;
}
static kern_return_t commit(struct owner *o,uint64_t seq,uint64_t *ack) {
    uint64_t in[]={WIDTH,HEIGHT,seq}; uint32_t count=1;
    kern_return_t r=IOConnectCallScalarMethod(o->connection,2,in,3,ack,&count);
    return r==KERN_SUCCESS && count!=1 ? kIOReturnError:r;
}
static void hold(unsigned seconds) { while(seconds-- && !interrupted)sleep(1); }
int main(int argc,char **argv) {
    unsigned seconds=0; char *end=NULL;
    if(argc==3 && !strcmp(argv[1],"--hold-seconds")) {
        errno=0; long n=strtol(argv[2],&end,10);
        if(errno || !*argv[2] || *end || n<0 || n>30)return 2;
        seconds=(unsigned)n;
    } else if(argc!=1)return 2;
    setvbuf(stdout,NULL,_IOLBF,0);
    signal(SIGALRM,interrupt_handler);signal(SIGTERM,interrupt_handler);signal(SIGINT,interrupt_handler);alarm(60);
    struct owner o[6]={0}; io_service_t service=0; int passed=0,clean=1;
    kern_return_t r=KERN_SUCCESS; const char *step="service"; uint64_t ack=0;
#define CHECK(c,label) do { step=label; if(interrupted || !(c))goto done; }while(0)
#define OPEN(i) CHECK((r=IOServiceOpen(service,mach_task_self(),0,&o[i].connection))==KERN_SUCCESS,"open")
#define ARM(i) CHECK((r=arm(&o[i]))==KERN_SUCCESS,"arm")
#define MAP(i) do { CHECK((r=IOConnectMapMemory64(o[i].connection,1,mach_task_self(),&o[i].address,&o[i].length,kIOMapAnywhere))==KERN_SUCCESS,"map-default"); CHECK(o[i].address && o[i].length==BYTES,"map-size"); }while(0)
    service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
    CHECK(service && property_one(service,CFSTR("SnapshotProtocol")) && property_one(service,CFSTR("SnapshotRestartable")),"capability");
    OPEN(0);ARM(0);MAP(0); CHECK((r=retire(&o[0]))==KERN_SUCCESS,"retire-A");
    r=commit(&o[0],1,&ack); printf("{\"check\":\"old-commit\",\"ioreturn\":%u}\n",(unsigned)r); CHECK(r!=KERN_SUCCESS,"old-commit-refused");
    r=arm(&o[0]);printf("{\"check\":\"old-rearm\",\"ioreturn\":%u}\n",(unsigned)r);CHECK(r!=KERN_SUCCESS,"same-connection-rearm-refused");
    OPEN(1);ARM(1);MAP(1);CHECK(zero_buffer(&o[1]),"fresh-B-zero");
    {
        mach_vm_address_t bad=0;mach_vm_size_t length=0;
        r=IOConnectMapMemory64(o[1].connection,1,mach_task_self(),&bad,&length,kIOMapAnywhere|kIOMapWriteCombineCache);
        if(r==KERN_SUCCESS)IOConnectUnmapMemory64(o[1].connection,1,mach_task_self(),bad);
        printf("{\"check\":\"WC-alias\",\"ioreturn\":%u}\n",(unsigned)r);
        CHECK(r!=KERN_SUCCESS,"WC-alias-refused");
    }
    uint32_t *p=(void *)(uintptr_t)o[1].address;
    for(unsigned y=0;y<HEIGHT;y++)for(unsigned x=0;x<WIDTH;x++)p[y*WIDTH+x]=pixel(x,y);
    memset((void *)(uintptr_t)o[0].address,0xa5,BYTES);fence();
    CHECK(mismatches(&o[1])==0,"stale-A-isolated-before-commit");
    CHECK((r=commit(&o[1],1,&ack))==KERN_SUCCESS && ack==1,"B-commit-ACK");
    printf("{\"phase\":\"published-before-stale-write\",\"width\":801,\"height\":601,\"ack\":%llu,\"mismatches\":0,\"hold_seconds\":%u}\n",(unsigned long long)ack,seconds/2);
    hold(seconds/2);
    memset((void *)(uintptr_t)o[0].address,0x5a,BYTES);fence();
    CHECK(mismatches(&o[1])==0,"stale-A-isolated-after-ACK");
    printf("{\"phase\":\"published-after-stale-write-no-new-commit\",\"ack\":1,\"mismatches\":0,\"hold_seconds\":%u}\n",seconds-seconds/2);
    hold(seconds-seconds/2);
    CHECK((r=retire(&o[1]))==KERN_SUCCESS,"retire-B");
    for(int i=2;i<4;i++){OPEN(i);ARM(i);MAP(i);CHECK((r=retire(&o[i]))==KERN_SUCCESS,"retire-cap-owner");}
    OPEN(4);r=arm(&o[4]);printf("{\"check\":\"four-retained-cap\",\"ioreturn\":%u}\n",(unsigned)r);CHECK(r!=KERN_SUCCESS,"four-retained-cap-refused");
    CHECK(cleanup(&o[4]),"close-cap-refusal");
    CHECK(cleanup(&o[0]),"release-A-capacity");
    OPEN(5);ARM(5);MAP(5);CHECK(zero_buffer(&o[5]),"recovered-slot-zero");
    passed=1;step="complete";
done:
    for(int i=5;i>=0;i--)if(!cleanup(&o[i]))clean=0;
    if(service)IOObjectRelease(service);alarm(0);
    printf("{\"phase\":\"result\",\"passed\":%s,\"step\":\"%s\",\"last_ioreturn\":%u,\"cleanup_ok\":%s,\"interrupted\":%s,\"retained_slot_limit\":4,\"scope\":\"private-staging-and-host-ACK-not-manager-delivery\"}\n",passed&&clean&&!interrupted?"true":"false",step,(unsigned)r,clean?"true":"false",interrupted?"true":"false");
    return passed&&clean&&!interrupted?0:1;
}
