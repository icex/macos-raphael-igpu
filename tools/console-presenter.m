// Copy complete ScreenCaptureKit frames into the presentation-only QEMU console.
// Compile with -fobjc-arc -fblocks and Foundation/AppKit/ScreenCaptureKit/IOKit/CoreMedia/CoreVideo.
#import <AppKit/AppKit.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <IOKit/IOKitLib.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#include <stdio.h>
#include <string.h>

@interface ConsoleOutput : NSObject <SCStreamOutput>
@property io_connect_t connection;
@property mach_vm_address_t address;
@property mach_vm_size_t length;
@property NSUInteger frames;
@property NSUInteger width;
@property NSUInteger height;
@property BOOL stopping;
@end
@implementation ConsoleOutput
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sample ofType:(SCStreamOutputType)type {
    if(self.stopping || type!=SCStreamOutputTypeScreen || !CMSampleBufferIsValid(sample))return;
    NSArray *attachments=(__bridge NSArray *)CMSampleBufferGetSampleAttachmentsArray(sample, false);
    if(!attachments.count || [attachments[0][SCStreamFrameInfoStatus] integerValue]!=SCFrameStatusComplete)return;
    CVPixelBufferRef image=CMSampleBufferGetImageBuffer(sample);
    if(!image || CVPixelBufferGetPixelFormatType(image)!=kCVPixelFormatType_32BGRA)return;
    size_t w=CVPixelBufferGetWidth(image),h=CVPixelBufferGetHeight(image);
    if(w!=self.width || h!=self.height || w*h*4>self.length)return;
    if(CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess)return;
    const uint8_t *src=CVPixelBufferGetBaseAddress(image);
    size_t stride=CVPixelBufferGetBytesPerRow(image);
    if(src && stride>=w*4) {
        for(size_t y=0;y<h;y++)memcpy((void *)(self.address+y*w*4),src+y*stride,w*4);
        self.frames++;
        if(self.frames==1 || self.frames%120==0) { printf("CONSOLE frame=%lu width=%zu height=%zu\n",(unsigned long)self.frames,w,h);fflush(stdout); }
    }
    CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly);
}
@end

int main(int argc,const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    if(argc!=4) { fprintf(stderr,"usage: console-presenter DISPLAY_ID|auto FPS SECONDS\n");return 2; }
    const bool autoDisplay=!strcmp(argv[1],"auto");
    __block unsigned did=(unsigned)strtoul(argv[1],NULL,10),fps=(unsigned)strtoul(argv[2],NULL,10),seconds=(unsigned)strtoul(argv[3],NULL,10);
    if((!did && !autoDisplay) || (fps!=30&&fps!=60&&fps!=120) || !seconds || seconds>6000)return 2;
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
    if(!service) { fprintf(stderr,"console device absent\n");return 3; }
    ConsoleOutput *out=[ConsoleOutput new];
    io_connect_t connection=IO_OBJECT_NULL;
    kern_return_t kr=IOServiceOpen(service,mach_task_self(),0,&connection);
    out.connection=connection;
    IOObjectRelease(service);
    if(kr) { fprintf(stderr,"console open: %x\n",kr);return 3; }
    mach_vm_address_t address=0;mach_vm_size_t length=0;
    kr=IOConnectMapMemory64(out.connection,0,mach_task_self(),&address,&length,kIOMapAnywhere);
    if(kr) { fprintf(stderr,"console map: %x\n",kr);IOServiceClose(out.connection);return 3; }
    out.address=address;out.length=length;
    __block SCStream *capture;
    dispatch_queue_t outputQueue=dispatch_queue_create("org.raphaelgpu.console",DISPATCH_QUEUE_SERIAL);
    [SCShareableContent getShareableContentExcludingDesktopWindows:NO onScreenWindowsOnly:NO completionHandler:^(SCShareableContent *content,NSError *error) {
        SCDisplay *display=nil;
        for(SCDisplay *item in content.displays) {
            bool match=autoDisplay ? (CGDisplayVendorNumber(item.displayID)==0x5250 &&
                CGDisplayModelNumber(item.displayID)==0x3453) : item.displayID==did;
            if(match) { if(display){fprintf(stderr,"ambiguous console display\n");exit(4);} display=item; }
        }
        if(display)did=display.displayID;
        if(error || !display) { fprintf(stderr,"capture unavailable: %s\n",error.description.UTF8String);exit(4); }
        CGDisplayModeRef mode=CGDisplayCopyDisplayMode(did);
        if(!mode)exit(4);
        out.width=CGDisplayModeGetPixelWidth(mode);out.height=CGDisplayModeGetPixelHeight(mode);CFRelease(mode);
        if(out.width>4096 || out.height>2304 || out.width*out.height*4>length)exit(4);
        memset((void *)address,0,out.width*out.height*4);
        uint64_t dims[]={out.width,out.height};
        kern_return_t result=IOConnectCallScalarMethod(out.connection,0,dims,2,NULL,NULL);
        if(result) { fprintf(stderr,"console mode: %x\n",result);exit(4); }
        SCStreamConfiguration *config=[SCStreamConfiguration new];
        config.width=out.width;config.height=out.height;config.pixelFormat=kCVPixelFormatType_32BGRA;
        config.minimumFrameInterval=CMTimeMake(1,fps);config.queueDepth=3;config.showsCursor=YES;
        SCContentFilter *filter=[[SCContentFilter alloc] initWithDisplay:display excludingWindows:@[]];
        capture=[[SCStream alloc] initWithFilter:filter configuration:config delegate:nil];
        NSError *addError=nil;
        if(![capture addStreamOutput:out type:SCStreamOutputTypeScreen sampleHandlerQueue:outputQueue error:&addError])exit(4);
        [capture startCaptureWithCompletionHandler:^(NSError *startError){
            if(startError) { fprintf(stderr,"capture start: %s\n",startError.description.UTF8String);exit(4); }
            printf("CONSOLE started display=%u size=%lux%lu requested_fps=%u\n",did,(unsigned long)out.width,(unsigned long)out.height,fps);fflush(stdout);
        }];
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)seconds*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        out.stopping=YES;
        if(!capture) {
            fprintf(stderr,"capture startup exceeded deadline\n");
            IOConnectUnmapMemory64(out.connection,0,mach_task_self(),address);
            IOServiceClose(out.connection);exit(5);
        }
        [capture stopCaptureWithCompletionHandler:^(NSError *error){
            dispatch_sync(outputQueue,^{}); // finish any already-running copy before unmap
            printf("CONSOLE completed frames=%lu\n",(unsigned long)out.frames);fflush(stdout);
            IOConnectUnmapMemory64(out.connection,0,mach_task_self(),address);IOServiceClose(out.connection);
            exit(error || !out.frames ? 5 : 0);
        }];
    });
    // A missing stop callback must not keep the helper alive beyond its budget.
    // Process exit releases the mapping/client without racing an explicit unmap.
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,((int64_t)seconds+2)*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        fprintf(stderr,"capture stop exceeded deadline\n");exit(5);
    });
    [[NSRunLoop currentRunLoop] run];
    return 0;
}}
