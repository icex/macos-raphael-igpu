// Present complete ScreenCaptureKit BGRA frames through the bounded Bochs client.
// All capture state, mode changes and mapped-memory access run on one serial queue.
#import <AppKit/AppKit.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <IOKit/IOKitLib.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#include <time.h>
#include <stdio.h>
#include <string.h>
#include <emmintrin.h>

static void displayChanged(CGDirectDisplayID display, CGDisplayChangeSummaryFlags flags, void *context) {
    printf("CONSOLE display_change=%u flags=0x%x\n",display,flags);fflush(stdout);
}

static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static SCStreamConfiguration *configuration(size_t w, size_t h, unsigned fps) {
    SCStreamConfiguration *c = [SCStreamConfiguration new];
    c.width=w; c.height=h; c.pixelFormat=kCVPixelFormatType_32BGRA;
    c.minimumFrameInterval=CMTimeMake(1,fps); c.queueDepth=3; c.showsCursor=YES;
    return c;
}
@interface ConsoleOutput : NSObject <SCStreamOutput, SCStreamDelegate>
@property io_connect_t connection;
@property mach_vm_address_t address;
@property mach_vm_size_t length;
@property NSUInteger frames, width, height, targetWidth, targetHeight, reportFrames;
@property double reportTime, copySeconds, maxCopySeconds;
@property BOOL stopping, updating, running;
@property NSUInteger dropped;
@property(strong) dispatch_queue_t processingQueue;
@property(strong) dispatch_semaphore_t copying;
@end
@implementation ConsoleOutput
- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
    fprintf(stderr,"capture stopped: %s\n",error.description.UTF8String); exit(5);
}
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sample ofType:(SCStreamOutputType)type {
    if(type!=SCStreamOutputTypeScreen || !CMSampleBufferIsValid(sample))return;
    // Keep at most one copy queued/running. Slow mappings must not accumulate
    // retained frames ahead of mode changes and shutdown on the control queue.
    if(dispatch_semaphore_wait(self.copying,DISPATCH_TIME_NOW)) { self.dropped++;return; }
    CFRetain(sample);
    dispatch_async(self.processingQueue,^{
        [self presentSample:sample];CFRelease(sample);dispatch_semaphore_signal(self.copying);
    });
}
- (void)presentSample:(CMSampleBufferRef)sample {
    if(self.stopping || self.updating)return;
    NSArray *attachments=(__bridge NSArray *)CMSampleBufferGetSampleAttachmentsArray(sample, false);
    if(!attachments.count || [attachments[0][SCStreamFrameInfoStatus] integerValue]!=SCFrameStatusComplete)return;
    CVPixelBufferRef image=CMSampleBufferGetImageBuffer(sample);
    if(!image || CVPixelBufferGetPixelFormatType(image)!=kCVPixelFormatType_32BGRA)return;
    size_t w=CVPixelBufferGetWidth(image),h=CVPixelBufferGetHeight(image);
    if(w!=self.targetWidth || h!=self.targetHeight || w*h*4>self.length)return;
    double begin=now();
    if(CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess)return;
    const uint8_t *src=CVPixelBufferGetBaseAddress(image);
    size_t stride=CVPixelBufferGetBytesPerRow(image);
    if(src && stride>=w*4) {
        for(size_t y=0;y<h;y++)memcpy((void *)(self.address+y*w*4),src+y*stride,w*4);
        _mm_sfence(); // publish write-combined stores before the mode or frame count
        if(w!=self.width || h!=self.height) {
            uint64_t dims[]={w,h};
            kern_return_t kr=IOConnectCallScalarMethod(self.connection,0,dims,2,NULL,NULL);
            if(kr) { fprintf(stderr,"console mode: %x\n",kr);exit(4); }
            self.width=w;self.height=h;
            printf("CONSOLE mode=%zux%zu\n",w,h);
        }
        double end=now(),duration=end-begin;
        self.frames++;self.reportFrames++;self.copySeconds+=duration;
        if(duration>self.maxCopySeconds)self.maxCopySeconds=duration;
        if(self.frames==1 || end-self.reportTime>=5) {
            printf("CONSOLE frames=%lu size=%zux%zu elapsed=%.3f copied_fps=%.2f copy_avg_ms=%.3f copy_max_ms=%.3f dropped=%lu\n",
                (unsigned long)self.frames,w,h,end-self.reportTime,
                self.reportFrames/(end-self.reportTime),1000*self.copySeconds/self.reportFrames,1000*self.maxCopySeconds,(unsigned long)self.dropped);
            self.reportTime=end;self.reportFrames=0;self.copySeconds=0;self.maxCopySeconds=0;fflush(stdout);
        }
    }
    CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly);
}
@end

static BOOL mode(CGDirectDisplayID did, mach_vm_size_t length, size_t *w, size_t *h) {
    if(!CGDisplayIsOnline(did))return NO;
    CGDisplayModeRef m=CGDisplayCopyDisplayMode(did);
    if(!m)return NO;
    *w=CGDisplayModeGetPixelWidth(m);*h=CGDisplayModeGetPixelHeight(m);CFRelease(m);
    return *w>=320 && *h>=200 && *w<=4096 && *h<=2304 && *w*(*h)*4<=length;
}
int main(int argc,const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    if(argc!=4) { fprintf(stderr,"usage: console-presenter DISPLAY_ID|auto FPS SECONDS\n");return 2; }
    const bool autoDisplay=!strcmp(argv[1],"auto");
    __block unsigned did=(unsigned)strtoul(argv[1],NULL,10);
    unsigned fps=(unsigned)strtoul(argv[2],NULL,10),seconds=(unsigned)strtoul(argv[3],NULL,10);
    if((!did && !autoDisplay) || (fps!=30&&fps!=60&&fps!=120) || !seconds || seconds>6000)return 2;
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
    if(!service) { fprintf(stderr,"console device absent\n");return 3; }
    ConsoleOutput *out=[ConsoleOutput new];
    io_connect_t connection=IO_OBJECT_NULL;
    kern_return_t kr=IOServiceOpen(service,mach_task_self(),0,&connection);
    IOObjectRelease(service);
    if(kr) { fprintf(stderr,"console open: %x\n",kr);return 3; }
    out.connection=connection;
    const char *cache=getenv("RGPU_CONSOLE_CACHE");
    IOOptionBits mapOptions=kIOMapAnywhere;
    if(cache && !strcmp(cache,"wc"))mapOptions|=kIOMapWriteCombineCache;
    else if(cache && strcmp(cache,"default"))return 2;
    printf("CONSOLE cache=%s\n",cache?cache:"default");fflush(stdout);
    mach_vm_address_t address=0;mach_vm_size_t length=0;
    kr=IOConnectMapMemory64(connection,0,mach_task_self(),&address,&length,mapOptions);
    if(kr) { fprintf(stderr,"console map: %x\n",kr);IOServiceClose(connection);return 3; }
    out.address=address;out.length=length;
    if(CGDisplayRegisterReconfigurationCallback(displayChanged,NULL)!=kCGErrorSuccess)return 4;
    __block SCStream *capture;
    dispatch_queue_t queue=dispatch_queue_create("org.raphaelgpu.console",DISPATCH_QUEUE_SERIAL);
    out.processingQueue=queue;out.copying=dispatch_semaphore_create(1);
    dispatch_queue_t captureQueue=dispatch_queue_create("org.raphaelgpu.console.capture",DISPATCH_QUEUE_SERIAL);
    dispatch_source_t timer=dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER,0,0,queue);
    dispatch_source_set_timer(timer,dispatch_time(DISPATCH_TIME_NOW,NSEC_PER_SEC),NSEC_PER_SEC/2,NSEC_PER_SEC/20);
    __block NSUInteger polls=0;
    dispatch_source_set_event_handler(timer,^{
        if(!out.running || out.stopping || out.updating)return;
        size_t w,h;
        if(!mode(did,length,&w,&h)) { fprintf(stderr,"console display disappeared or unsupported mode\n");exit(4); }
        if(++polls%20==1) {printf("CONSOLE mode_poll=%zux%zu\n",w,h);fflush(stdout);}
        if(w==out.targetWidth && h==out.targetHeight)return;
        out.updating=YES;
        [capture updateConfiguration:configuration(w,h,fps) completionHandler:^(NSError *error){
            dispatch_async(queue,^{
                if(out.stopping)return;
                if(error) { fprintf(stderr,"capture resize: %s\n",error.description.UTF8String);exit(4); }
                out.targetWidth=w;out.targetHeight=h;out.updating=NO;
                printf("CONSOLE capture_resize=%zux%zu\n",w,h);fflush(stdout);
            });
        }];
    });
    dispatch_resume(timer);
    [SCShareableContent getShareableContentExcludingDesktopWindows:NO onScreenWindowsOnly:NO completionHandler:^(SCShareableContent *content,NSError *error) {
        dispatch_async(queue,^{
            if(out.stopping)return;
            SCDisplay *display=nil;
            for(SCDisplay *item in content.displays) {
                bool match=autoDisplay ? (CGDisplayVendorNumber(item.displayID)==0x5250 &&
                    CGDisplayModelNumber(item.displayID)==0x3453) : item.displayID==did;
                if(match) { if(display){fprintf(stderr,"ambiguous console display\n");exit(4);}display=item; }
            }
            if(error || !display) { fprintf(stderr,"capture unavailable: %s\n",error.description.UTF8String);exit(4); }
            did=display.displayID;size_t w,h;
            if(!mode(did,length,&w,&h))exit(4);
            out.targetWidth=w;out.targetHeight=h;out.reportTime=now();
            SCContentFilter *filter=[[SCContentFilter alloc] initWithDisplay:display excludingWindows:@[]];
            capture=[[SCStream alloc] initWithFilter:filter configuration:configuration(w,h,fps) delegate:out];
            NSError *addError=nil;
            if(![capture addStreamOutput:out type:SCStreamOutputTypeScreen sampleHandlerQueue:captureQueue error:&addError])exit(4);
            [capture startCaptureWithCompletionHandler:^(NSError *startError){
                if(startError) { fprintf(stderr,"capture start: %s\n",startError.description.UTF8String);exit(4); }
                dispatch_async(queue,^{out.running=YES;});
                printf("CONSOLE started display=%u size=%zux%zu requested_fps=%u\n",did,w,h,fps);fflush(stdout);
            }];
        });
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)seconds*NSEC_PER_SEC),queue,^{
        out.stopping=YES;dispatch_source_cancel(timer);
        if(!capture) { fprintf(stderr,"capture startup exceeded deadline\n");exit(5); }
        [capture stopCaptureWithCompletionHandler:^(NSError *error){
            dispatch_async(queue,^{
                printf("CONSOLE completed frames=%lu\n",(unsigned long)out.frames);fflush(stdout);
                IOConnectUnmapMemory64(connection,0,mach_task_self(),address);IOServiceClose(connection);
                exit(error || !out.frames ? 5 : 0);
            });
        }];
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,((int64_t)seconds+2)*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        fprintf(stderr,"capture stop exceeded deadline\n");exit(5);
    });
    [[NSRunLoop currentRunLoop] run];return 0;
}}
