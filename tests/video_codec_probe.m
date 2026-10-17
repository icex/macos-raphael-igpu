// One codec per process. Run only inside a supervised experiment.
// Build: clang -fobjc-arc video_codec_probe.m -framework Foundation
//        -framework VideoToolbox -framework CoreMedia -framework CoreVideo -o probe
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <signal.h>
#include <unistd.h>

static NSMutableArray *samples;
static unsigned decoded, errors;
static uint64_t differences, checked;
static unsigned maxDifference;
static const int width = 1280, height = 720, frameCount = 3;

static void emit(NSString *phase, NSDictionary *fields) {
    NSMutableDictionary *record = [fields mutableCopy];
    record[@"phase"] = phase;
    record[@"pid"] = @(getpid());
    record[@"epoch"] = @([[NSDate date] timeIntervalSince1970]);
    NSData *data = [NSJSONSerialization dataWithJSONObject:record options:0 error:NULL];
    @synchronized(samples ?: (id)[NSNull null]) {
        fwrite(data.bytes, 1, data.length, stdout);
        fputc('\n', stdout);
        fflush(stdout);
    }
}
static void expired(int sig) {
    (void)sig;
    const char message[] = "{\"phase\":\"deadline\",\"passed\":false}\n";
    write(STDOUT_FILENO, message, sizeof(message)-1);
    _exit(124);
}
static uint8_t luma(int x, int y, int frame) {
    return 32 + 40*(x >= width/2) + 80*(y >= height/2) + 5*frame;
}
static void encoded(void *context, void *source, OSStatus status,
                    VTEncodeInfoFlags flags, CMSampleBufferRef sample) {
    (void)context; (void)source;
    @autoreleasepool {
        emit(@"encode-callback", @{@"status":@(status), @"flags":@(flags),
             @"bytes":@(sample ? CMSampleBufferGetTotalSampleSize(sample) : 0)});
        if (status || !sample || !CMSampleBufferDataIsReady(sample)) { errors++; return; }
        @synchronized(samples) { [samples addObject:(__bridge id)sample]; }
    }
}
static void decodedFrame(void *context, void *source, OSStatus status,
                         VTDecodeInfoFlags flags, CVImageBufferRef image,
                         CMTime pts, CMTime duration) {
    (void)context; (void)source; (void)flags; (void)duration;
    @autoreleasepool {
        if (status || !image || CVPixelBufferGetPixelFormatType(image) !=
            kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange ||
            CVPixelBufferGetWidth(image) != width || CVPixelBufferGetHeight(image) != height) {
            errors++; emit(@"decode-error", @{@"status":@(status)}); return;
        }
        CVReturn lock = CVPixelBufferLockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
        if (lock) { errors++; return; }
        const uint8_t *ybase = CVPixelBufferGetBaseAddressOfPlane(image, 0);
        size_t stride = CVPixelBufferGetBytesPerRowOfPlane(image, 0);
        int frame = (int)CMTimeConvertScale(pts, 30, kCMTimeRoundingMethod_Default).value;
        // Exclude a narrow band at hard edges: lossy encoder ringing is expected there.
        for (int y=4;y<height-4;y++) for (int x=4;x<width-4;x++) {
            if (abs(x-width/2)<4 || abs(y-height/2)<4) continue;
            unsigned delta = abs((int)ybase[y*stride+x] - luma(x,y,frame));
            differences += delta; checked++;
            if (delta > maxDifference) maxDifference=delta;
        }
        CVPixelBufferUnlockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
        decoded++;
        emit(@"decode-callback", @{@"status":@(status), @"frame":@(frame),
                                  @"max_luma_error":@(maxDifference)});
    }
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        signal(SIGALRM, expired); alarm(90);
        samples = [NSMutableArray array];
        if (argc == 2 && !strcmp(argv[1], "--list")) {
            CFArrayRef list=NULL;
            OSStatus s=VTCopyVideoEncoderList(NULL, &list);
            // Apple's list contains property-list values; descriptions retain all keys.
            emit(@"encoder-list", @{@"status":@(s), @"encoders":list ?
                 [(__bridge NSArray *)list description] : @""});
            if (list) CFRelease(list);
            return s ? 1 : 0;
        }
        if (argc != 4 || (strcmp(argv[1], "h264") && strcmp(argv[1], "hevc")) ||
            (strcmp(argv[2], "hw") && strcmp(argv[2], "sw"))) {
            fprintf(stderr,"usage: probe h264|hevc hw|sw registryID (0 for sw), or --list\n");
            return 2;
        }
        BOOL hardware = !strcmp(argv[2], "hw");
        uint64_t registry = strtoull(argv[3], NULL, 0);
        if (hardware && !registry) return 2;
        CMVideoCodecType codec = !strcmp(argv[1],"hevc") ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264;
        NSMutableDictionary *spec = [@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(hardware)} mutableCopy];
        if (hardware) {
            spec[(__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder]=@YES;
            spec[(__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID]=@(registry);
        }
        NSDictionary *attrs=@{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
            (__bridge id)kCVPixelBufferWidthKey:@(width), (__bridge id)kCVPixelBufferHeightKey:@(height),
            (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        emit(@"create-begin", @{@"codec":@(argv[1]), @"hardware_requested":@(hardware),
                               @"registry_id":@(registry), @"width":@(width), @"height":@(height)});
        VTCompressionSessionRef session=NULL;
        OSStatus status=VTCompressionSessionCreate(NULL,width,height,codec,(__bridge CFDictionaryRef)spec,
            (__bridge CFDictionaryRef)attrs,NULL,encoded,NULL,&session);
        emit(@"create-end", @{@"status":@(status)});
        if (status || !session) return 1;
        status=VTSessionSetProperty(session,kVTCompressionPropertyKey_AllowFrameReordering,kCFBooleanFalse);
        emit(@"set-reordering", @{@"status":@(status)});
        emit(@"prepare-begin", @{});
        status=VTCompressionSessionPrepareToEncodeFrames(session);
        emit(@"prepare-end", @{@"status":@(status)});
        if (status) { VTCompressionSessionInvalidate(session); CFRelease(session); return 1; }
        CFTypeRef actual=NULL, encoderID=NULL;
        VTSessionCopyProperty(session,kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder,NULL,&actual);
        VTSessionCopyProperty(session,kVTCompressionPropertyKey_EncoderID,NULL,&encoderID);
        BOOL actualHardware=actual && CFEqual(actual,kCFBooleanTrue);
        emit(@"selected-encoder", @{@"hardware":@(actualHardware), @"encoder_id":encoderID ?
             [(__bridge id)encoderID description] : @"unknown"});
        if (actual) CFRelease(actual); if (encoderID) CFRelease(encoderID);
        if (actualHardware != hardware) errors++;
        for (int frame=0;frame<frameCount;frame++) {
            CVPixelBufferRef pixel=NULL;
            status=CVPixelBufferCreate(NULL,width,height,kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                (__bridge CFDictionaryRef)attrs,&pixel);
            if (status) { errors++; break; }
            status=CVPixelBufferLockBaseAddress(pixel,0);
            if (status) { CVPixelBufferRelease(pixel); errors++; break; }
            uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(pixel,0);
            size_t stride=CVPixelBufferGetBytesPerRowOfPlane(pixel,0);
            for(int y=0;y<height;y++) for(int x=0;x<width;x++) base[y*stride+x]=luma(x,y,frame);
            uint8_t *uv=CVPixelBufferGetBaseAddressOfPlane(pixel,1);
            size_t uvstride=CVPixelBufferGetBytesPerRowOfPlane(pixel,1);
            for(int y=0;y<height/2;y++) memset(uv+y*uvstride,128,width);
            CVPixelBufferUnlockBaseAddress(pixel,0);
            emit(@"encode-begin", @{@"frame":@(frame)});
            status=VTCompressionSessionEncodeFrame(session,pixel,CMTimeMake(frame,30),CMTimeMake(1,30),NULL,NULL,NULL);
            emit(@"encode-end", @{@"frame":@(frame), @"status":@(status)});
            CVPixelBufferRelease(pixel);
            if(status) { errors++; break; }
        }
        emit(@"flush-begin", @{});
        status=VTCompressionSessionCompleteFrames(session,kCMTimeInvalid);
        emit(@"flush-end", @{@"status":@(status), @"samples":@(samples.count)});
        if(status) errors++;
        emit(@"invalidate-begin", @{});
        VTCompressionSessionInvalidate(session); CFRelease(session);
        emit(@"invalidate-end", @{});
        // Software decode keeps the roundtrip check independent of GPU decode support.
        if(samples.count) {
            VTDecompressionSessionRef decoder=NULL;
            VTDecompressionOutputCallbackRecord callback={decodedFrame,NULL};
            NSDictionary *decodeSpec=@{(__bridge id)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@NO};
            CMSampleBufferRef first=(__bridge CMSampleBufferRef)samples[0];
            status=VTDecompressionSessionCreate(NULL,CMSampleBufferGetFormatDescription(first),
                (__bridge CFDictionaryRef)decodeSpec,(__bridge CFDictionaryRef)attrs,&callback,&decoder);
            emit(@"decoder-create", @{@"status":@(status)});
            if(!status && decoder) {
                for(id sample in samples) {
                    status=VTDecompressionSessionDecodeFrame(decoder,(__bridge CMSampleBufferRef)sample,0,NULL,NULL);
                    if(status) errors++;
                }
                status=VTDecompressionSessionWaitForAsynchronousFrames(decoder);
                if(status) errors++;
                VTDecompressionSessionInvalidate(decoder); CFRelease(decoder);
            } else errors++;
        }
        BOOL passed=!errors && samples.count==frameCount && decoded==frameCount && checked && maxDifference<=8;
        emit(@"result", @{@"passed":@(passed), @"errors":@(errors), @"encoded_frames":@(samples.count),
             @"decoded_frames":@(decoded), @"luma_values_checked":@(checked),
             @"max_luma_error":@(maxDifference), @"mean_luma_error":@(checked ? (double)differences/checked : 0)});
        alarm(0);
        return passed ? 0 : 1;
    }
}
