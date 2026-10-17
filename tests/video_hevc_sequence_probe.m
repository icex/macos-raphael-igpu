// Replicate the exact decode ordering that succeeded in run 5cb7876d, in one process:
//   H.264 software-encode -> H.264 hardware-decode, then
//   HEVC hardware-encode  -> HEVC hardware-decode.
// The question: does HEVC hardware decode succeed when it is NOT the first decode
// context of a clean boot, and no HEVC decode has failed first?
// Build: clang -fobjc-arc video_hevc_sequence_probe.m -framework Foundation
//        -framework VideoToolbox -framework CoreMedia -framework CoreVideo -o probe
//   probe <registryID>
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <signal.h>
#include <unistd.h>

static NSMutableArray *samples;
static unsigned decoded, decodeErrors, maxDifference;
static const int width = 1280, height = 720, frameCount = 3;

static void emit(NSString *phase, NSDictionary *fields) {
    NSMutableDictionary *r = [fields mutableCopy];
    r[@"phase"] = phase; r[@"pid"] = @(getpid());
    NSData *d = [NSJSONSerialization dataWithJSONObject:r options:0 error:NULL];
    @synchronized(samples ?: (id)[NSNull null]) { fwrite(d.bytes,1,d.length,stdout); fputc('\n',stdout); fflush(stdout); }
}
static void expired(int s){(void)s; const char m[]="{\"phase\":\"deadline\"}\n"; write(2,m,sizeof(m)-1); _exit(124);}
static uint8_t luma(int x,int y,int f){return 32+40*(x>=width/2)+80*(y>=height/2)+5*f;}
static void encoded(void *c,void *s,OSStatus st,VTEncodeInfoFlags fl,CMSampleBufferRef sb){
    (void)c;(void)s;(void)fl;
    @autoreleasepool { if(st||!sb||!CMSampleBufferDataIsReady(sb))return; @synchronized(samples){[samples addObject:(__bridge id)sb];} }
}
static void decodedFrame(void *c,void *s,OSStatus st,VTDecodeInfoFlags fl,CVImageBufferRef img,CMTime pts,CMTime dur){
    (void)c;(void)s;(void)fl;(void)dur;
    @autoreleasepool {
        if(st||!img){decodeErrors++;emit(@"decode-error",@{@"status":@(st)});return;}
        if(CVPixelBufferLockBaseAddress(img,kCVPixelBufferLock_ReadOnly)){decodeErrors++;return;}
        const uint8_t *y=CVPixelBufferGetBaseAddressOfPlane(img,0);
        size_t st2=CVPixelBufferGetBytesPerRowOfPlane(img,0);
        int f=(int)CMTimeConvertScale(pts,30,kCMTimeRoundingMethod_Default).value;
        for(int j=4;j<height-4;j++)for(int i=4;i<width-4;i++){
            if(abs(i-width/2)<4||abs(j-height/2)<4)continue;
            unsigned dd=abs((int)y[j*st2+i]-luma(i,j,f)); if(dd>maxDifference)maxDifference=dd;
        }
        CVPixelBufferUnlockBaseAddress(img,kCVPixelBufferLock_ReadOnly); decoded++;
        emit(@"decode-callback",@{@"frame":@(f),@"max_luma_error":@(maxDifference)});
    }
}
static NSDictionary *attrs(void){
    return @{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
             (__bridge id)kCVPixelBufferWidthKey:@(width),(__bridge id)kCVPixelBufferHeightKey:@(height),
             (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
}
static BOOL encode(CMVideoCodecType codec,BOOL hw,uint64_t reg){
    [samples removeAllObjects];
    NSMutableDictionary *spec=[@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(hw)} mutableCopy];
    if(hw){spec[(__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder]=@YES;
           spec[(__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID]=@(reg);}
    VTCompressionSessionRef s=NULL;
    OSStatus st=VTCompressionSessionCreate(NULL,width,height,codec,(__bridge CFDictionaryRef)spec,
        (__bridge CFDictionaryRef)attrs(),NULL,encoded,NULL,&s);
    if(st||!s){emit(@"encode-create",@{@"codec":@(codec),@"status":@(st)});return NO;}
    VTSessionSetProperty(s,kVTCompressionPropertyKey_AllowFrameReordering,kCFBooleanFalse);
    VTCompressionSessionPrepareToEncodeFrames(s);
    CFTypeRef eid=NULL; VTSessionCopyProperty(s,kVTCompressionPropertyKey_EncoderID,NULL,&eid);
    emit(@"selected-encoder",@{@"codec":@(codec),@"hardware":@(hw),@"encoder_id":eid?[(__bridge id)eid description]:@"?"});
    if(eid)CFRelease(eid);
    for(int f=0;f<frameCount;f++){
        CVPixelBufferRef px=NULL; if(CVPixelBufferCreate(NULL,width,height,kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,(__bridge CFDictionaryRef)attrs(),&px))return NO;
        CVPixelBufferLockBaseAddress(px,0);
        uint8_t *b=CVPixelBufferGetBaseAddressOfPlane(px,0); size_t str=CVPixelBufferGetBytesPerRowOfPlane(px,0);
        for(int y=0;y<height;y++)for(int x=0;x<width;x++)b[y*str+x]=luma(x,y,f);
        uint8_t *uv=CVPixelBufferGetBaseAddressOfPlane(px,1); size_t us=CVPixelBufferGetBytesPerRowOfPlane(px,1);
        for(int y=0;y<height/2;y++)memset(uv+y*us,128,width);
        CVPixelBufferUnlockBaseAddress(px,0);
        VTCompressionSessionEncodeFrame(s,px,CMTimeMake(f,30),CMTimeMake(1,30),NULL,NULL,NULL);
        CVPixelBufferRelease(px);
    }
    VTCompressionSessionCompleteFrames(s,kCMTimeInvalid);
    VTCompressionSessionInvalidate(s); CFRelease(s);
    return samples.count==frameCount;
}
static BOOL decode(NSString *tag,uint64_t reg){
    decoded=0;decodeErrors=0;maxDifference=0;
    CMFormatDescriptionRef desc=CMSampleBufferGetFormatDescription((__bridge CMSampleBufferRef)samples[0]);
    NSMutableDictionary *spec=[NSMutableDictionary dictionary];
    spec[(__bridge id)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder]=@YES;
    spec[(__bridge id)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder]=@YES;
    if(reg)spec[(__bridge id)kVTVideoDecoderSpecification_RequiredDecoderGPURegistryID]=@(reg);
    VTDecompressionOutputCallbackRecord cb={decodedFrame,NULL};
    VTDecompressionSessionRef dec=NULL;
    OSStatus st=VTDecompressionSessionCreate(NULL,desc,(__bridge CFDictionaryRef)spec,(__bridge CFDictionaryRef)attrs(),&cb,&dec);
    BOOL sel=NO;
    if(!st&&dec){
        CFTypeRef u=NULL; VTSessionCopyProperty(dec,kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,NULL,&u);
        sel=u&&CFEqual(u,kCFBooleanTrue); if(u)CFRelease(u);
        for(id s in samples)VTDecompressionSessionDecodeFrame(dec,(__bridge CMSampleBufferRef)s,0,NULL,NULL);
        VTDecompressionSessionWaitForAsynchronousFrames(dec);
        VTDecompressionSessionInvalidate(dec);CFRelease(dec);
    }
    emit(@"decode",@{@"tag":tag,@"create_status":@(st),@"hardware":@(sel),@"decoded":@(decoded),
                     @"errors":@(decodeErrors),@"max_luma_error":@(maxDifference)});
    return !st&&sel&&decoded==frameCount&&!decodeErrors;
}
int main(int argc,const char**argv){
    @autoreleasepool{
        setbuf(stdout,NULL); signal(SIGALRM,expired); alarm(160);
        samples=[NSMutableArray array];
        if(argc!=2)return 2;
        uint64_t reg=strtoull(argv[1],NULL,0); if(!reg)return 2;
        // 1. H.264 sw-encode -> hw-decode (first decode context of the boot, like 5cb7876d).
        BOOL a=encode(kCMVideoCodecType_H264,NO,reg) && decode(@"h264-sw-stream",0);
        // 2. H.264 hw-encode -> hw-decode.
        BOOL b=encode(kCMVideoCodecType_H264,YES,reg) && decode(@"h264-hw-stream",0);
        // 3. HEVC hw-encode -> hw-decode (the operation that worked in 5cb7876d).
        BOOL c=encode(kCMVideoCodecType_HEVC,YES,reg) && decode(@"hevc-hw-stream",0);
        // 4. HEVC hw-encode -> hw-decode WITH the registry id, for contrast.
        BOOL d=encode(kCMVideoCodecType_HEVC,YES,reg) && decode(@"hevc-hw-stream-registry",reg);
        emit(@"result",@{@"h264":@(a),@"h264hw":@(b),@"hevc":@(c),@"hevc_registry":@(d)});
        return (a&&b&&c)?0:1;
    }
}
