// Own CPU pixels only: no screen capture or physical GPU access.
#import <Foundation/Foundation.h>
#import <IOSurface/IOSurface.h>
#import <CoreVideo/CoreVideo.h>
#import <IOKit/IOKitLib.h>
#include <emmintrin.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static double stamp(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static uint32_t pixel(size_t x,size_t y,unsigned phase) {
    return 0xff000000u|(((x+phase*37)&255)<<16)|(((y+phase*71)&255)<<8)|((x^y^phase)&255);
}
static unsigned number(const char *s) {char *end=NULL;unsigned long n=strtoul(s,&end,10);return *s&&end&&!*end&&n<=4096?(unsigned)n:0;}
int main(int argc,const char **argv) { @autoreleasepool {
    // Fixed small matrix; CLI intentionally accepts only the two qualified sizes.
    if(argc!=5){fprintf(stderr,"usage: console-copy-probe ram|console 1920|3840 1080|2160 HOLD_SECONDS(0..15)\n");return 2;}
    bool console=!strcmp(argv[1],"console");
    if(!console&&strcmp(argv[1],"ram"))return 2;
    size_t w=number(argv[2]),h=number(argv[3]);unsigned hold=number(argv[4]);
    if((w!=1920||h!=1080)&&(w!=3840||h!=2160))return 2;
    if(hold>15||(!hold&&strcmp(argv[4],"0")))return 2;
    alarm(60); // Hard process bound, including allocation, lock and optional hold.
    size_t row=w*4,bytes=row*h;
    void *cpu=NULL,*ram=NULL;io_connect_t client=IO_OBJECT_NULL;
    mach_vm_address_t mapping=0;mach_vm_size_t length=0;
    IOSurfaceRef surface=NULL;CVPixelBufferRef buffer=NULL;int result=3;unsigned lastPhase=0;
    if(posix_memalign(&cpu,64,bytes)||posix_memalign(&ram,64,bytes))goto done;
    memset(cpu,0,bytes);memset(ram,0,bytes);
    surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{(id)kIOSurfaceWidth:@(w),(id)kIOSurfaceHeight:@(h),
        (id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(row),
        (id)kIOSurfaceAllocSize:@(bytes),(id)kIOSurfacePixelFormat:@(kCVPixelFormatType_32BGRA)});
    if(!surface||CVPixelBufferCreateWithIOSurface(kCFAllocatorDefault,surface,NULL,&buffer)!=kCVReturnSuccess)goto done;
    if(CVPixelBufferGetWidth(buffer)!=w||CVPixelBufferGetHeight(buffer)!=h||
       CVPixelBufferIsPlanar(buffer)||CVPixelBufferGetPixelFormatType(buffer)!=kCVPixelFormatType_32BGRA)goto done;
    if(console) {
        io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
        if(!service)goto done;
        kern_return_t kr=IOServiceOpen(service,mach_task_self(),0,&client);IOObjectRelease(service);
        if(kr)goto done;
        // Only the existing exclusive presentation client memory0, never physical Raphael BARs.
        if(IOConnectMapMemory64(client,0,mach_task_self(),&mapping,&length,
            kIOMapAnywhere|kIOMapWriteCombineCache)||length<bytes)goto done;
    }
    for(unsigned round=0;round<3;round++)for(unsigned order=0;order<4;order++) {
        unsigned which=round%2?3-order:order,kind=which/2;bool contiguous=which%2;
        size_t stride=row;uint8_t *src=cpu;bool locked=false;
        if(kind) {
            if(CVPixelBufferLockBaseAddress(buffer,0)!=kCVReturnSuccess)goto done;
            locked=true;src=CVPixelBufferGetBaseAddress(buffer);stride=CVPixelBufferGetBytesPerRow(buffer);
        }
        if(!src||stride<row||stride>SIZE_MAX/h||(kind&&IOSurfaceGetAllocSize(surface)<stride*h)) {
            if(locked)CVPixelBufferUnlockBaseAddress(buffer,0);goto done;
        }
        unsigned phase=round*4+which;
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++)((uint32_t *)(src+y*stride))[x]=pixel(x,y,phase);
        if(locked&&CVPixelBufferUnlockBaseAddress(buffer,0)!=kCVReturnSuccess)goto done;
        if(contiguous&&stride!=row) {
            printf("COPY_SKIP source=iosurface method=contiguous stride=%zu row=%zu\n",stride,row);continue;
        }
        uint8_t *dest=console?(uint8_t *)mapping:ram;
        double start=stamp();
        if(kind&&CVPixelBufferLockBaseAddress(buffer,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess)goto done;
        double lockEnd=stamp();
        if(kind)src=CVPixelBufferGetBaseAddress(buffer);
        if(!src) {if(kind)CVPixelBufferUnlockBaseAddress(buffer,kCVPixelBufferLock_ReadOnly);goto done;}
        double copyStart=stamp();
        if(contiguous)memcpy(dest,src,bytes);
        else for(size_t y=0;y<h;y++)memcpy(dest+y*row,src+y*stride,row);
        double copyEnd=stamp();_mm_sfence();double fenceEnd=stamp();
        CVReturn unlock=kind?CVPixelBufferUnlockBaseAddress(buffer,kCVPixelBufferLock_ReadOnly):kCVReturnSuccess;
        double end=stamp();if(unlock!=kCVReturnSuccess)goto done;
        // Readback is deliberately outside timings; volatile reads include every destination pixel.
        volatile const uint32_t *actual=(volatile const uint32_t *)dest;
        uint64_t bad=0;
        for(size_t y=0;y<h;y++)for(size_t x=0;x<w;x++)if(actual[y*w+x]!=pixel(x,y,phase))bad++;
        printf("COPY target=%s source=%s method=%s round=%u warmup=%u phase=%u width=%zu height=%zu bytes=%zu stride=%zu lock_ms=%.6f copy_ms=%.6f sfence_ms=%.6f unlock_ms=%.6f total_ms=%.6f bad_pixels=%llu\n",
            argv[1],kind?"iosurface-cvpixelbuffer":"malloc",contiguous?"contiguous":"rows",round,round==0,phase,w,h,bytes,stride,
            1000*(lockEnd-start),1000*(copyEnd-copyStart),1000*(fenceEnd-copyEnd),1000*(end-fenceEnd),1000*(end-start),(unsigned long long)bad);
        fflush(stdout);if(bad){result=4;goto done;}lastPhase=phase;
    }
    if(console) {uint64_t dims[]={w,h};if(IOConnectCallScalarMethod(client,0,dims,2,NULL,NULL))goto done;}
    printf("COPY_READY width=%zu height=%zu phase=%u hold=%u\n",w,h,lastPhase,hold);fflush(stdout);
    sleep(hold);result=0;
done:
    if(mapping)IOConnectUnmapMemory64(client,0,mach_task_self(),mapping);
    if(client)IOServiceClose(client);
    if(buffer)CFRelease(buffer);if(surface)CFRelease(surface);free(cpu);free(ram);
    printf("COPY_EXIT result=%d\n",result);return result;
}}
