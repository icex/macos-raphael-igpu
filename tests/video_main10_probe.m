// Bounded Main10 4:2:0 qualification; run under the experiment supervisor.
// probe hw|sw encoderRegistry frames width height (max 16 frames / 1080p).
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <signal.h>
#include <unistd.h>
#include <string.h>
#include <stdlib.h>

static NSMutableArray *samples, *referenceY, *referenceUV;
static NSMutableIndexSet *seen;
static BOOL referenceMode;
static unsigned errors, decoded, referenceFrames;
static uint64_t yChecked, cChecked, yBad, cBad, patternBad, nonEightBit;
static unsigned maxY, maxC, maxPattern;
static int width, height, frames;
static const unsigned referenceTolerance = 2, patternTolerance = 48;

static void emit(NSString *phase, NSDictionary *fields) {
    @synchronized(samples) {
        NSMutableDictionary *r = [fields mutableCopy];
        r[@"phase"] = phase; r[@"pid"] = @(getpid());
        NSData *d = [NSJSONSerialization dataWithJSONObject:r options:0 error:NULL];
        fwrite(d.bytes, 1, d.length, stdout); fputc('\n', stdout); fflush(stdout);
    }
}
static BOOL check(NSString *phase, OSStatus status) {
    emit(phase, @{@"status":@(status)});
    if (status) { @synchronized(samples) { errors++; } }
    return status == 0;
}
static void expired(int sig) {
    (void)sig;
    const char s[] = "{\"phase\":\"deadline\",\"passed\":false}\n";
    write(STDOUT_FILENO, s, sizeof(s)-1); _exit(124);
}
// Odd codes exercise lower bits. Actual fidelity is measured against software
// decoding of the same compressed stream, separately from lossy pattern checks.
static uint16_t yValue(int x, int y, int f) {
    return 101 + 278*(x >= width/2) + 322*(y >= height/2) + 7*(f % 5);
}
static uint16_t cbValue(int x, int y, int f) { (void)y; return 137 + 3*(f%5) + 11*(x >= width/2); }
static uint16_t crValue(int x, int y, int f) { (void)x; return 701 + 5*(f%5) + 13*(y >= height/2); }
static uint16_t sample10(const uint8_t *p) { uint16_t v; memcpy(&v,p,2); return v >> 6; }
static BOOL interior(int x,int y) {
    return x>=4 && x<width-4 && y>=4 && y<height-4 &&
           abs(x-width/2)>=8 && abs(y-height/2)>=8;
}
static BOOL layout(CVPixelBufferRef p) {
    return CVPixelBufferGetPixelFormatType(p)==kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange &&
        CVPixelBufferGetWidth(p)==width && CVPixelBufferGetHeight(p)==height &&
        CVPixelBufferGetPlaneCount(p)==2 && CVPixelBufferGetWidthOfPlane(p,0)==width &&
        CVPixelBufferGetHeightOfPlane(p,0)==height &&
        CVPixelBufferGetWidthOfPlane(p,1)==width/2 && CVPixelBufferGetHeightOfPlane(p,1)==height/2 &&
        CVPixelBufferGetBytesPerRowOfPlane(p,0)>=2*width && CVPixelBufferGetBytesPerRowOfPlane(p,1)>=2*width;
}
static void encoded(void *ctx,void *src,OSStatus status,VTEncodeInfoFlags flags,CMSampleBufferRef sample) {
    (void)ctx; (void)src; (void)flags;
    @autoreleasepool { @synchronized(samples) {
        if(status || !sample || !CMSampleBufferDataIsReady(sample)) {
            errors++; emit(@"encode-callback-error",@{@"status":@(status)}); return;
        }
        [samples addObject:(__bridge id)sample];
    } }
}
static void decodedFrame(void *ctx,void *src,OSStatus status,VTDecodeInfoFlags flags,
                         CVImageBufferRef image,CMTime pts,CMTime duration) {
    (void)ctx; (void)src; (void)flags; (void)duration;
    @autoreleasepool { @synchronized(samples) {
        if(status || !image || !layout(image) || !CMTIME_IS_NUMERIC(pts)) {
            errors++; emit(@"decode-callback-error",@{@"status":@(status),@"reference":@(referenceMode)}); return;
        }
        CMTime t=CMTimeConvertScale(pts,30,kCMTimeRoundingMethod_Default);
        int f=(int)t.value;
        if(f<0 || f>=frames || CMTimeCompare(pts,CMTimeMake(f,30)) || [seen containsIndex:f]) {
            errors++; emit(@"frame-identity-error",@{@"frame":@(f)}); return;
        }
        if(!check(@"lock-output",CVPixelBufferLockBaseAddress(image,kCVPixelBufferLock_ReadOnly))) return;
        [seen addIndex:f];
        for(int plane=0;plane<2;plane++) {
            size_t stride=CVPixelBufferGetBytesPerRowOfPlane(image,plane);
            const uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(image,plane);
            int rows=plane ? height/2 : height;
            NSMutableArray *refs=plane ? referenceUV : referenceY;
            if(!base) { errors++; continue; }
            NSMutableData *packed=referenceMode ? [NSMutableData dataWithLength:(size_t)rows*width*2] : nil;
            NSData *ref=referenceMode ? nil : refs[f];
            if(!referenceMode && ![ref isKindOfClass:[NSData class]]) { errors++; continue; }
            for(int y=0;y<rows;y++) {
                if(referenceMode) memcpy((uint8_t *)packed.mutableBytes+(size_t)y*width*2,base+y*stride,width*2);
                for(int x=0;x<width;x++) {
                    unsigned actual=sample10(base+y*stride+2*x);
                    if(referenceMode) {
                        if(actual & 3) nonEightBit++;
                        int px=plane ? x & ~1 : x, py=plane ? y*2 : y;
                        unsigned expected=plane ? ((x&1) ? crValue(px,py,f) : cbValue(px,py,f)) : yValue(px,py,f);
                        if(interior(px,py)) {
                            unsigned delta=abs((int)actual-(int)expected);
                            if(delta>maxPattern) maxPattern=delta;
                            if(delta>patternTolerance) patternBad++;
                        }
                    } else {
                        unsigned expected=sample10((const uint8_t *)ref.bytes+((size_t)y*width+x)*2);
                        unsigned delta=abs((int)actual-(int)expected);
                        if(plane) { cChecked++; if(delta>maxC) maxC=delta; if(delta>referenceTolerance) cBad++; }
                        else { yChecked++; if(delta>maxY) maxY=delta; if(delta>referenceTolerance) yBad++; }
                    }
                }
            }
            if(referenceMode) refs[f]=packed;
        }
        check(@"unlock-output",CVPixelBufferUnlockBaseAddress(image,kCVPixelBufferLock_ReadOnly));
        decoded++;
    } }
}
static BOOL validateMain10(CMFormatDescriptionRef desc) {
    NSDictionary *ext=(__bridge NSDictionary *)CMFormatDescriptionGetExtensions(desc);
    NSDictionary *atoms=ext[(__bridge id)kCMFormatDescriptionExtension_SampleDescriptionExtensionAtoms];
    NSData *data=atoms[@"hvcC"];
    if(![data isKindOfClass:[NSData class]] || data.length<23) return NO;
    const uint8_t *b=data.bytes;
    emit(@"format",@{@"hvcC_bytes":@(data.length),@"profile_idc":@(b[1]&31),
        @"chroma_format":@(b[16]&3),@"luma_bit_depth":@(8+(b[17]&7)),@"chroma_bit_depth":@(8+(b[18]&7))});
    return b[0]==1 && (b[1]&31)==2 && (b[16]&3)==1 && (b[17]&7)==2 && (b[18]&7)==2;
}
static BOOL selection(VTSessionRef session,CFStringRef key,BOOL expected,NSString *phase) {
    CFTypeRef value=NULL; OSStatus s=VTSessionCopyProperty(session,key,NULL,&value);
    BOOL valid=!s && value && CFGetTypeID(value)==CFBooleanGetTypeID();
    BOOL hardware=valid && CFEqual(value,kCFBooleanTrue);
    emit(phase,@{@"status":@(s),@"property_valid":@(valid),@"hardware":@(hardware)});
    if(value) CFRelease(value);
    // The VCP software encoder returns PropertyNotSupported for this property.
    // Accept that exact case only when the independently queried encoder ID is
    // the explicitly requested VCP implementation; hardware still needs true.
    if(!expected && s==kVTPropertyNotSupportedErr &&
       CFEqual(key,kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder)) {
        CFTypeRef encoderID=NULL;
        OSStatus idStatus=VTSessionCopyProperty(session,kVTCompressionPropertyKey_EncoderID,NULL,&encoderID);
        BOOL software=!idStatus && encoderID && CFEqual(encoderID,CFSTR("com.apple.videotoolbox.videoencoder.hevc.vcp"));
        emit(@"software-encoder-identity",@{@"status":@(idStatus),@"matched":@(software),
            @"encoder_id":encoderID ? [(__bridge id)encoderID description] : @"missing"});
        if(encoderID) CFRelease(encoderID);
        if(software) return YES;
    }
    if(!valid || hardware!=expected) { errors++; return NO; }
    return YES;
}
static BOOL decode(CMFormatDescriptionRef desc,NSDictionary *attrs,BOOL hardware) {
    referenceMode=!hardware; decoded=0; [seen removeAllIndexes];
    NSMutableDictionary *spec=[@{(__bridge id)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@(hardware)} mutableCopy];
    if(hardware) spec[(__bridge id)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder]=@YES;
    VTDecompressionOutputCallbackRecord cb={decodedFrame,NULL}; VTDecompressionSessionRef session=NULL;
    OSStatus s=VTDecompressionSessionCreate(NULL,desc,(__bridge CFDictionaryRef)spec,(__bridge CFDictionaryRef)attrs,&cb,&session);
    if(!check(hardware ? @"hardware-decoder-create" : @"software-decoder-create",s) || !session) return NO;
    BOOL selected=selection(session,kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,hardware,@"selected-decoder");
    if(selected) for(id sample in samples)
        check(@"decode-submit",VTDecompressionSessionDecodeFrame(session,(__bridge CMSampleBufferRef)sample,0,NULL,NULL));
    check(@"decode-finish",VTDecompressionSessionFinishDelayedFrames(session));
    check(@"decode-wait",VTDecompressionSessionWaitForAsynchronousFrames(session));
    VTDecompressionSessionInvalidate(session); CFRelease(session);
    BOOL complete=selected && decoded==frames && seen.count==frames;
    emit(@"decode-pass-end",@{@"hardware":@(hardware),@"frames":@(decoded),@"unique":@(seen.count),@"complete":@(complete)});
    if(!complete) errors++;
    return complete;
}
int main(int argc,const char **argv) {
    @autoreleasepool {
        setbuf(stdout,NULL); signal(SIGALRM,expired); alarm(180);
        samples=[NSMutableArray array]; seen=[NSMutableIndexSet indexSet];
        referenceY=[NSMutableArray array]; referenceUV=[NSMutableArray array];
        if(argc!=6 || (strcmp(argv[1],"hw") && strcmp(argv[1],"sw"))) return 2;
        BOOL hardware=!strcmp(argv[1],"hw"); uint64_t registry=strtoull(argv[2],NULL,0);
        frames=atoi(argv[3]); width=atoi(argv[4]); height=atoi(argv[5]);
        if(frames<1 || frames>16 || width<64 || width>1920 || height<64 || height>1080 ||
           (width&1) || (height&1) || (hardware && !registry)) return 2;
        for(int i=0;i<frames;i++) { [referenceY addObject:[NSNull null]]; [referenceUV addObject:[NSNull null]]; }
        emit(@"begin",@{@"frames":@(frames),@"width":@(width),@"height":@(height),@"hardware_encoder_requested":@(hardware)});
        NSDictionary *attrs=@{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange),
            (__bridge id)kCVPixelBufferWidthKey:@(width),(__bridge id)kCVPixelBufferHeightKey:@(height),
            (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        NSMutableDictionary *spec=[@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(hardware)} mutableCopy];
        if(hardware) { spec[(__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder]=@YES;
            spec[(__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID]=@(registry); }
        if(!hardware) spec[(__bridge id)kVTVideoEncoderSpecification_EncoderID]=@"com.apple.videotoolbox.videoencoder.hevc.vcp";
        VTCompressionSessionRef enc=NULL;
        OSStatus s=VTCompressionSessionCreate(NULL,width,height,kCMVideoCodecType_HEVC,(__bridge CFDictionaryRef)spec,
                                             (__bridge CFDictionaryRef)attrs,NULL,encoded,NULL,&enc);
        if(!check(@"encoder-create",s) || !enc) return 1;
        BOOL ready=check(@"set-reordering",VTSessionSetProperty(enc,kVTCompressionPropertyKey_AllowFrameReordering,kCFBooleanFalse));
        ready=check(@"set-main10",VTSessionSetProperty(enc,kVTCompressionPropertyKey_ProfileLevel,kVTProfileLevel_HEVC_Main10_AutoLevel)) && ready;
        ready=check(@"encoder-prepare",VTCompressionSessionPrepareToEncodeFrames(enc)) && ready;
        ready=selection(enc,kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder,hardware,@"selected-encoder") && ready;
        if(ready) for(int f=0;f<frames;f++) { @autoreleasepool {
            CVPixelBufferRef p=NULL;
            if(!check(@"create-input",CVPixelBufferCreate(NULL,width,height,kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange,(__bridge CFDictionaryRef)attrs,&p))) break;
            if(!layout(p)) { errors++; CVPixelBufferRelease(p); break; }
            if(!check(@"lock-input",CVPixelBufferLockBaseAddress(p,0))) { CVPixelBufferRelease(p); break; }
            for(int plane=0;plane<2;plane++) {
                uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(p,plane); size_t stride=CVPixelBufferGetBytesPerRowOfPlane(p,plane);
                int rows=plane ? height/2 : height;
                for(int y=0;y<rows;y++) for(int x=0;x<width;x++) {
                    uint16_t v=(plane ? ((x&1) ? crValue(x&~1,y*2,f) : cbValue(x&~1,y*2,f)) : yValue(x,y,f))<<6;
                    memcpy(base+y*stride+2*x,&v,2);
                }
            }
            check(@"unlock-input",CVPixelBufferUnlockBaseAddress(p,0));
            check(@"encode-submit",VTCompressionSessionEncodeFrame(enc,p,CMTimeMake(f,30),CMTimeMake(1,30),NULL,NULL,NULL));
            CVPixelBufferRelease(p);
        } }
        check(@"encode-complete",VTCompressionSessionCompleteFrames(enc,kCMTimeInvalid));
        VTCompressionSessionInvalidate(enc); CFRelease(enc);
        BOOL formatOK=samples.count==frames;
        for(id sample in samples) if(!validateMain10(CMSampleBufferGetFormatDescription((__bridge CMSampleBufferRef)sample))) formatOK=NO;
        if(!formatOK) errors++;
        BOOL hardwareComplete=NO;
        if(!errors && formatOK) {
            CMFormatDescriptionRef desc=CMSampleBufferGetFormatDescription((__bridge CMSampleBufferRef)samples[0]);
            BOOL referenceComplete=decode(desc,attrs,NO); referenceFrames=decoded;
            if(referenceComplete && !errors) hardwareComplete=decode(desc,attrs,YES);
        }
        BOOL passed=!errors && formatOK && hardwareComplete && !patternBad && !yBad && !cBad && nonEightBit &&
            yChecked==(uint64_t)width*height*frames && cChecked==(uint64_t)width*height*frames/2;
        emit(@"result",@{@"passed":@(passed),@"errors":@(errors),@"hardware_decoder_complete":@(hardwareComplete),
            @"encoded_frames":@(samples.count),@"reference_frames":@(referenceFrames),@"decoded_frames":@(decoded),
            @"luma_checked":@(yChecked),@"chroma_checked":@(cChecked),@"luma_bad":@(yBad),@"chroma_bad":@(cBad),
            @"max_luma_reference_error":@(maxY),@"max_chroma_reference_error":@(maxC),@"reference_tolerance":@(referenceTolerance),
            @"pattern_bad":@(patternBad),@"max_pattern_error":@(maxPattern),@"pattern_tolerance":@(patternTolerance),
            @"reference_non_8bit_codes":@(nonEightBit)});
        alarm(0); return passed ? 0 : 1;
    }
}
