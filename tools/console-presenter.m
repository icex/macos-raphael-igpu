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
#include <stdlib.h>
#include <emmintrin.h>
#include "console-source-token.h"

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
// Processing-queue-owned statistics. Durations are wall time, not CPU time.
enum { TimingQueue, TimingLock, TimingRows, TimingFence, TimingMode,
       TimingUnlock, TimingTotal, TimingCount };
typedef struct {
    double start, sum[TimingCount], maximum[TimingCount];
    uint64_t frames, bytes, transitions;
    size_t width, height, strideMin, strideMax;
} ConsoleTiming;
@interface ConsoleOutput : NSObject <SCStreamOutput, SCStreamDelegate> {
    ConsoleTiming timing;
    RGTokenWindow tokenWindow;
    unsigned sourceSamples[2];
    uint8_t *sourceScratch;
    uint64_t droppedCount; // atomic: capture queue writes, processing queue reads
}
@property io_connect_t connection;
@property mach_vm_address_t address;
@property mach_vm_size_t length;
@property NSUInteger frames, width, height, targetWidth, targetHeight, reportFrames;
@property double reportTime, copySeconds, maxCopySeconds;
@property BOOL stopping, updating, running;
@property BOOL snapshot, snapshotArmed;
@property uint64_t snapshotSequence;
@property(strong) dispatch_queue_t processingQueue;
@property(strong) dispatch_semaphore_t copying;
@end
@implementation ConsoleOutput
- (BOOL)configureToken:(const char *)nonce {
    if(!nonce)return YES;
    if(!rg_token_nonce(nonce,tokenWindow.nonce))return NO;
    tokenWindow.enabled=1;
    printf("CONSOLE_SOURCE_TOKEN configured=1 wait_seconds=60 window_seconds=30 scope=processed-source-only excludes=busy-dropped,upstream-uncaptured,scanout\n");fflush(stdout);return YES;
}
- (void)armToken {
    if(tokenWindow.enabled){tokenWindow.armed=1;tokenWindow.armedAt=now();}
}
- (void)pollToken {
    rg_token_poll(&tokenWindow,now());
    if(tokenWindow.enabled&&tokenWindow.done&&!tokenWindow.reported){
        tokenWindow.reported=1;
        printf("CONSOLE_SOURCE_TOKEN done=1 outcome=%s reported_at=%.9f last_sequence=%u started=%d armed_at=%.9f start=%.9f end=%.9f waiting=%llu processed=%llu valid=%llu invalid=%llu unique=%llu duplicates=%llu skipped_ids=%llu scale=%u check_total_ms=%.3f check_max_ms=%.3f",
          tokenWindow.interrupted?"interrupted":(tokenWindow.started?"complete-window":"no-valid-timeout"),now(),tokenWindow.last,
          tokenWindow.started,tokenWindow.armedAt,tokenWindow.start,tokenWindow.end,
          (unsigned long long)tokenWindow.waiting,(unsigned long long)tokenWindow.processed,
          (unsigned long long)tokenWindow.valid,(unsigned long long)tokenWindow.invalid,
          (unsigned long long)tokenWindow.unique,(unsigned long long)tokenWindow.duplicates,
          (unsigned long long)tokenWindow.skipped,tokenWindow.scale,1000*tokenWindow.checkSeconds,1000*tokenWindow.checkMax);
        for(unsigned i=1;i<RG_T_RESULTS;i++)printf(" error_%u=%llu",i,(unsigned long long)tokenWindow.errors[i]);
        printf("\n");fflush(stdout);
    }
}
- (void)tokenUnavailable {
    if(tokenWindow.enabled){rg_token_observe(&tokenWindow,now(),RG_T_UNAVAILABLE,0,0);[self pollToken];}
}
- (void)checkToken:(const uint8_t *)pixels width:(size_t)w height:(size_t)h stride:(size_t)stride {
    if(!tokenWindow.enabled||!tokenWindow.armed||tokenWindow.done)return;
    double begin=now();rg_token_poll(&tokenWindow,begin);if(tokenWindow.done){[self pollToken];return;}
    uint32_t sequence=0;unsigned scale=tokenWindow.started?tokenWindow.scale:1;
    int result=rg_token_decode(pixels,w,h,stride,tokenWindow.nonce,scale,&sequence);
    if(!tokenWindow.started&&result!=RG_T_VALID){scale=2;result=rg_token_decode(pixels,w,h,stride,tokenWindow.nonce,scale,&sequence);}
    int started=tokenWindow.started;
    rg_token_observe(&tokenWindow,begin,result,sequence,scale);
    double cost=now()-begin;tokenWindow.checkSeconds+=cost;if(cost>tokenWindow.checkMax)tokenWindow.checkMax=cost;
    if(!started&&tokenWindow.started){printf("CONSOLE_SOURCE_TOKEN started=1 sequence=%u scale=%u time=%.9f\n",sequence,scale,begin);fflush(stdout);}
    [self pollToken];
}
- (void)finishToken {
    if(tokenWindow.enabled&&!tokenWindow.done){printf("CONSOLE_SOURCE_TOKEN interrupted=presenter-stop\n");tokenWindow.interrupted=1;tokenWindow.done=1;tokenWindow.end=now();}
    [self pollToken];
}

- (BOOL)enableSourceDiagnostic {
    // Allocate/touch once before starting capture, never inside measured legs.
    if(posix_memalign((void **)&sourceScratch,64,3840u*2160u*4u))return NO;
    memset(sourceScratch,0,3840u*2160u*4u);return YES;
}
- (void)dealloc {free(sourceScratch);}
- (void)diagnoseSource:(const uint8_t *)src stride:(size_t)stride width:(size_t)w height:(size_t)h index:(unsigned)index {
    unsigned sample=sourceSamples[index],first=sample%2;
    size_t row=w*4;double direct=0,read=0,write=0,df=0,wf=0;
    double start=now();
    for(unsigned leg=0;leg<2;leg++) {
        if((leg^first)==0) {
            double a=now();
            for(size_t y=0;y<h;y++)memcpy((void *)(self.address+y*row),src+y*stride,row);
            double b=now();_mm_sfence();double c=now();direct=b-a;df=c-b;
        } else {
            double a=now();
            for(size_t y=0;y<h;y++)memcpy(sourceScratch+y*row,src+y*stride,row);
            double b=now();read=b-a;
            for(size_t y=0;y<h;y++)memcpy((void *)(self.address+y*row),sourceScratch+y*row,row);
            double c=now();_mm_sfence();double d=now();write=c-b;wf=d-c;
        }
    }
    double legsEnd=now();uint64_t bad=0;
    // Outside leg timings. Full volatile destination comparison is intentionally costly.
    volatile const uint8_t *dest=(volatile const uint8_t *)self.address;
    for(size_t i=0;i<row*h;i++)if(dest[i]!=sourceScratch[i])bad++;
    double end=now();sourceSamples[index]++;
    printf("CONSOLE_SOURCE_DIAG size=%zux%zu sample=%u order=%s bytes=%zu stride=%zu direct_ms=%.3f direct_sfence_ms=%.3f source_ram_ms=%.3f ram_wc_ms=%.3f ram_sfence_ms=%.3f legs_ms=%.3f verify_ms=%.3f extra_work_total_ms=%.3f bad_bytes=%llu\n",
        w,h,sample,first?"staged-first":"direct-first",row*h,stride,
        1000*direct,1000*df,1000*read,1000*write,1000*wf,1000*(legsEnd-start),1000*(end-legsEnd),1000*(end-start),(unsigned long long)bad);
    fflush(stdout);
    if(bad){fprintf(stderr,"console source diagnostic comparison failed\n");exit(6);}
}
- (void)stream:(SCStream *)stream didStopWithError:(NSError *)error {
    fprintf(stderr,"capture stopped: %s\n",error.description.UTF8String); exit(5);
}
- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sample ofType:(SCStreamOutputType)type {
    if(type!=SCStreamOutputTypeScreen || !CMSampleBufferIsValid(sample))return;
    double callbackTime=now();
    // Keep at most one copy queued/running. Slow mappings must not accumulate
    // retained frames ahead of mode changes and shutdown on the control queue.
    if(dispatch_semaphore_wait(self.copying,DISPATCH_TIME_NOW)) { __atomic_fetch_add(&droppedCount,1,__ATOMIC_RELAXED);return; }
    CFRetain(sample);
    dispatch_async(self.processingQueue,^{
        [self presentSample:sample callbackTime:callbackTime];CFRelease(sample);dispatch_semaphore_signal(self.copying);
    });
}
- (void)presentSample:(CMSampleBufferRef)sample callbackTime:(double)callbackTime {
    double workerTime=now();
    // Capture callbacks can precede start completion. Control and copies share
    // this queue; never write before staging is armed and mapped.
    if(self.snapshot && !self.snapshotArmed)return;
    if(self.stopping || self.updating){if(tokenWindow.enabled)[self tokenUnavailable];return;}
    NSArray *attachments=(__bridge NSArray *)CMSampleBufferGetSampleAttachmentsArray(sample, false);
    if(!attachments.count || [attachments[0][SCStreamFrameInfoStatus] integerValue]!=SCFrameStatusComplete){if(tokenWindow.enabled)[self tokenUnavailable];return;}
    CVPixelBufferRef image=CMSampleBufferGetImageBuffer(sample);
    if(!image || CVPixelBufferGetPixelFormatType(image)!=kCVPixelFormatType_32BGRA){if(tokenWindow.enabled)[self tokenUnavailable];return;}
    size_t w=CVPixelBufferGetWidth(image),h=CVPixelBufferGetHeight(image);
    if(w!=self.targetWidth || h!=self.targetHeight || w*h*4>self.length){if(tokenWindow.enabled)[self tokenUnavailable];return;}
    double begin=now();
    if(CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly)!=kCVReturnSuccess){if(tokenWindow.enabled)[self tokenUnavailable];return;}
    double locked=now();
    const uint8_t *src=CVPixelBufferGetBaseAddress(image);
    size_t stride=CVPixelBufferGetBytesPerRow(image);
    if(tokenWindow.enabled)[self checkToken:src width:w height:h stride:stride];
    BOOL copied=NO, changed=NO, diagnostic=NO;
    double rowsBegin=0, rowsEnd=0, fenced=0, modeBegin=0, modeEnd=0, end=0;
    if(src && stride>=w*4) {
        rowsBegin=now();
        int diagnosticIndex=(w==1920&&h==1080)?0:((w==3840&&h==2160)?1:-1);
        diagnostic=sourceScratch&&diagnosticIndex>=0&&sourceSamples[diagnosticIndex]<8&&w==self.width&&h==self.height;
        if(diagnostic)[self diagnoseSource:src stride:stride width:w height:h index:(unsigned)diagnosticIndex];
        else for(size_t y=0;y<h;y++)memcpy((void *)(self.address+y*w*4),src+y*stride,w*4);
        rowsEnd=now();
        _mm_sfence(); // publish write-combined stores before the mode or frame count
        fenced=now();
        changed=(w!=self.width || h!=self.height);
        modeBegin=now();
        if(self.snapshot) {
            uint64_t request[]={w,h,self.snapshotSequence+1},ack=0;
            uint32_t count=1;
            kern_return_t kr=IOConnectCallScalarMethod(self.connection,2,request,3,&ack,&count);
            if(kr || count!=1 || ack!=request[2]) {
                fprintf(stderr,"snapshot commit failed: %x sequence=%llu ack=%llu count=%u\n",
                    kr,(unsigned long long)request[2],(unsigned long long)ack,count);
                // Never retry or reuse staging after an ambiguous ACK.
                exit(4);
            }
            self.snapshotSequence=ack;
        } else if(changed) {
            uint64_t dims[]={w,h};
            kern_return_t kr=IOConnectCallScalarMethod(self.connection,0,dims,2,NULL,NULL);
            if(kr) { fprintf(stderr,"console mode: %x\n",kr);exit(4); }
        }
        if(changed) {
            self.width=w;self.height=h;
            printf("CONSOLE mode=%zux%zu\n",w,h);
        }
        modeEnd=now();
        end=now();
        double duration=end-begin;
        copied=YES;
        self.frames++;self.reportFrames++;self.copySeconds+=duration;
        if(duration>self.maxCopySeconds)self.maxCopySeconds=duration;

    }
    double unlockBegin=now();
    CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly);
    double unlocked=now();
    if(!copied)return;
    if(self.frames==1 || end-self.reportTime>=5) {
        if(self.snapshot)printf("CONSOLE_SNAPSHOT acknowledged=%llu scope=host-copy-not-delivery\n",
            (unsigned long long)self.snapshotSequence);
        printf("CONSOLE frames=%lu size=%zux%zu elapsed=%.3f copied_fps=%.2f copy_avg_ms=%.3f copy_max_ms=%.3f dropped=%lu\n",
            (unsigned long)self.frames,w,h,end-self.reportTime,
            self.reportFrames/(end-self.reportTime),1000*self.copySeconds/self.reportFrames,1000*self.maxCopySeconds,(unsigned long)__atomic_load_n(&droppedCount,__ATOMIC_RELAXED));
        self.reportTime=end;self.reportFrames=0;self.copySeconds=0;self.maxCopySeconds=0;fflush(stdout);
    }
    // Diagnostic copies retain legacy counts, but never enter steady stage statistics.
    if(diagnostic) {
        if(timing.start)[self reportTiming:unlocked];
        return;
    }
    // A geometry transition ends the preceding window; never mix resolutions.
    if(timing.start && changed) {
        [self reportTiming:unlocked];
    }
    if(!timing.start) {
        timing.start=workerTime;timing.width=w;timing.height=h;
        timing.strideMin=stride;timing.strideMax=stride;
    }
    if(changed) {
        timing.transitions++;
        // Transition cost has its own count; exclude the entire frame from steady statistics.
        printf("CONSOLE_TIMING_MODE size=%zux%zu mode_ms=%.3f total_ms=%.3f\n",
               w,h,1000*(modeEnd-modeBegin),1000*(unlocked-workerTime));
        return;
    }
    double values[TimingCount]={workerTime-callbackTime,locked-begin,
        rowsEnd-rowsBegin,fenced-rowsEnd,modeEnd-modeBegin,
        unlocked-unlockBegin,unlocked-workerTime};
    timing.frames++;timing.bytes+=(uint64_t)w*h*4;
    if(stride<timing.strideMin)timing.strideMin=stride;
    if(stride>timing.strideMax)timing.strideMax=stride;
    for(unsigned i=0;i<TimingCount;i++) {
        timing.sum[i]+=values[i];
        if(values[i]>timing.maximum[i])timing.maximum[i]=values[i];
    }
    if(unlocked-timing.start>=5)[self reportTiming:unlocked];
}
- (void)reportTiming:(double)end {
    static const char *names[]={"queue","lock","rows","sfence","mode_check","unlock","worker_total"};
    printf("CONSOLE_TIMING size=%zux%zu window_s=%.3f steady_frames=%llu bytes=%llu stride_min=%zu stride_max=%zu excluded_mode_frames=%llu",
           timing.width,timing.height,end-timing.start,
           (unsigned long long)timing.frames,(unsigned long long)timing.bytes,
           timing.strideMin,timing.strideMax,(unsigned long long)timing.transitions);
    for(unsigned i=0;i<TimingCount;i++) {
        const char *name=(self.snapshot && i==TimingMode)?"snapshot_commit":names[i];
        printf(" %s_avg_ms=%.3f %s_max_ms=%.3f",name,
               timing.frames?1000*timing.sum[i]/timing.frames:0,name,1000*timing.maximum[i]);
    }
    printf("\n");fflush(stdout);memset(&timing,0,sizeof(timing));
}
@end

static BOOL mode(CGDirectDisplayID did, mach_vm_size_t length, size_t *w, size_t *h, BOOL snapshot) {
    if(!CGDisplayIsOnline(did))return NO;
    CGDisplayModeRef m=CGDisplayCopyDisplayMode(did);
    if(!m)return NO;
    *w=CGDisplayModeGetPixelWidth(m);*h=CGDisplayModeGetPixelHeight(m);CFRelease(m);
    return *w>=320 && *h>=200 && *w<=(snapshot?3840:4096) &&
        *h<=(snapshot?2160:2304) && *w*(*h)*4<=length;
}
int main(int argc,const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    if(argc!=4) { fprintf(stderr,"usage: console-presenter DISPLAY_ID|auto FPS SECONDS\n");return 2; }
    const bool autoDisplay=!strcmp(argv[1],"auto");
    __block unsigned did=(unsigned)strtoul(argv[1],NULL,10);
    unsigned fps=(unsigned)strtoul(argv[2],NULL,10),seconds=(unsigned)strtoul(argv[3],NULL,10);
    if((!did && !autoDisplay) || (fps!=30&&fps!=60&&fps!=120) || !seconds || seconds>6000)return 2;
    const char *tokenNonce=getenv("RGPU_CONSOLE_TOKEN_NONCE");
    uint8_t tokenNonceCheck[8];
    if(tokenNonce&&!rg_token_nonce(tokenNonce,tokenNonceCheck)){fprintf(stderr,"invalid RGPU_CONSOLE_TOKEN_NONCE (exact16hex required)\n");return 2;}
    const char *snapshotSetting=getenv("RGPU_CONSOLE_SNAPSHOT");
    if(snapshotSetting&&strcmp(snapshotSetting,"0")&&strcmp(snapshotSetting,"1"))return 2;
    const bool snapshot=snapshotSetting&&!strcmp(snapshotSetting,"1");
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
    if(!service) { fprintf(stderr,"console device absent\n");return 3; }
    const char *sourceDiagnostic=getenv("RGPU_CONSOLE_SOURCE_DIAGNOSTIC");
    if(sourceDiagnostic&&strcmp(sourceDiagnostic,"0")&&strcmp(sourceDiagnostic,"1"))return 2;
    if(snapshot && sourceDiagnostic && !strcmp(sourceDiagnostic,"1"))return 2;
    if(snapshot) {
        CFTypeRef property=IORegistryEntryCreateCFProperty(service,CFSTR("SnapshotProtocol"),kCFAllocatorDefault,0);
        int protocol=0;
        bool supported=property&&CFGetTypeID(property)==CFNumberGetTypeID()&&
            CFNumberGetValue((CFNumberRef)property,kCFNumberIntType,&protocol)&&protocol==1;
        if(property)CFRelease(property);
        if(!supported){fprintf(stderr,"snapshot protocol unavailable\n");IOObjectRelease(service);return 3;}
    }
    ConsoleOutput *out=[ConsoleOutput new];
    out.snapshot=snapshot;
    if(![out configureToken:tokenNonce]){fprintf(stderr,"invalid RGPU_CONSOLE_TOKEN_NONCE (exact16hex required)\n");return 2;}
    if(sourceDiagnostic&&!strcmp(sourceDiagnostic,"1")) {
        if(![out enableSourceDiagnostic])return 3;
        printf("CONSOLE source_diagnostic=1 samples_per_geometry=8 legacy_timings_include_extra_work=1\n");fflush(stdout);
    }
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
    __block mach_vm_address_t address=0;
    __block mach_vm_size_t length=snapshot?32u*1024u*1024u:0;
    const uint32_t memoryType=snapshot?1:0;
    if(!snapshot) {
        kr=IOConnectMapMemory64(connection,0,mach_task_self(),&address,&length,mapOptions);
        if(kr) { fprintf(stderr,"console map: %x\n",kr);IOServiceClose(connection);return 3; }
    }
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
        [out pollToken];
        if(!out.running || out.stopping || out.updating)return;
        size_t w,h;
        if(!mode(did,length,&w,&h,snapshot)) { fprintf(stderr,"console display disappeared or unsupported mode\n");exit(4); }
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
            if(!mode(did,length,&w,&h,snapshot))exit(4);
            out.targetWidth=w;out.targetHeight=h;out.reportTime=now();
            SCContentFilter *filter=[[SCContentFilter alloc] initWithDisplay:display excludingWindows:@[]];
            capture=[[SCStream alloc] initWithFilter:filter configuration:configuration(w,h,fps) delegate:out];
            NSError *addError=nil;
            if(![capture addStreamOutput:out type:SCStreamOutputTypeScreen sampleHandlerQueue:captureQueue error:&addError])exit(4);
            [capture startCaptureWithCompletionHandler:^(NSError *startError){
                if(startError) { fprintf(stderr,"capture start: %s\n",startError.description.UTF8String);exit(4); }
                dispatch_async(queue,^{
                    if(out.stopping)return;
                    if(snapshot) {
                        // TCC/content/start failures must not consume the one-shot
                        // staging lease. Queued samples are ignored until ready.
                        kern_return_t armed=IOConnectCallScalarMethod(connection,1,NULL,0,NULL,NULL);
                        if(armed){fprintf(stderr,"snapshot arm: %x\n",armed);exit(4);}
                        kern_return_t mapped=IOConnectMapMemory64(connection,memoryType,mach_task_self(),&address,&length,mapOptions);
                        if(mapped || !address || length!=32u*1024u*1024u) {
                            fprintf(stderr,"snapshot staging map: %x bytes=%llu\n",mapped,(unsigned long long)length);
                            IOConnectCallScalarMethod(connection,3,NULL,0,NULL,NULL);
                            IOServiceClose(connection);exit(4);
                        }
                        out.address=address;out.length=length;out.snapshotArmed=YES;
                        printf("CONSOLE_SNAPSHOT armed=1 bytes=%llu lease=one-shot\n",(unsigned long long)length);
                    }
                    out.running=YES;[out armToken];
                    printf("CONSOLE started display=%u size=%zux%zu requested_fps=%u\n",did,w,h,fps);fflush(stdout);
                });
            }];
        });
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,(int64_t)seconds*NSEC_PER_SEC),queue,^{
        out.stopping=YES;[out finishToken];dispatch_source_cancel(timer);
        if(!capture) { fprintf(stderr,"capture startup exceeded deadline\n");exit(5); }
        [capture stopCaptureWithCompletionHandler:^(NSError *error){
            dispatch_async(queue,^{
                printf("CONSOLE completed frames=%lu\n",(unsigned long)out.frames);fflush(stdout);
                if(address)IOConnectUnmapMemory64(connection,memoryType,mach_task_self(),address);
                if(out.snapshotArmed)IOConnectCallScalarMethod(connection,3,NULL,0,NULL,NULL);
                IOServiceClose(connection);
                exit(error || !out.frames ? 5 : 0);
            });
        }];
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,((int64_t)seconds+2)*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        fprintf(stderr,"capture stop exceeded deadline\n");exit(5);
    });
    [[NSRunLoop currentRunLoop] run];return 0;
}}
