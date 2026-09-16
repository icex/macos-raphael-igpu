// HEVC format-description investigation. Run only inside a supervised experiment.
// Build: clang -fobjc-arc video_hevc_format_probe.m -framework Foundation
//        -framework VideoToolbox -framework CoreMedia -framework CoreVideo -o probe
//
//   probe variants   <registryID> <dir>   software (vcp) encode, dump hvcC, decode variants,
//                                         write the stream to <dir>/stream.bin
//   probe variants-hw <registryID> <dir>  hardware (gva) encode, dump hvcC, hardware decode
//   probe decodefile <registryID> <dir>   fresh process: hardware-decode <dir>/stream.bin
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <signal.h>
#include <unistd.h>

static NSMutableArray *samples;
static unsigned decoded, decodeErrors;
static unsigned maxDifference;
static const int width = 1280, height = 720, frameCount = 3;

static void emit(NSString *phase, NSDictionary *fields) {
    NSMutableDictionary *record = [fields mutableCopy];
    record[@"phase"] = phase;
    record[@"pid"] = @(getpid());
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
static NSString *hex(NSData *d) {
    NSMutableString *s = [NSMutableString string];
    const uint8_t *b = d.bytes;
    for (NSUInteger i = 0; i < d.length; i++) [s appendFormat:@"%02x", b[i]];
    return s;
}
static void encoded(void *context, void *source, OSStatus status,
                    VTEncodeInfoFlags flags, CMSampleBufferRef sample) {
    (void)context; (void)source;
    @autoreleasepool {
        emit(@"encode-callback", @{@"status":@(status), @"flags":@(flags),
             @"bytes":@(sample ? CMSampleBufferGetTotalSampleSize(sample) : 0)});
        if (status || !sample || !CMSampleBufferDataIsReady(sample)) return;
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
            decodeErrors++; emit(@"decode-error", @{@"status":@(status)}); return;
        }
        if (CVPixelBufferLockBaseAddress(image, kCVPixelBufferLock_ReadOnly)) { decodeErrors++; return; }
        const uint8_t *ybase = CVPixelBufferGetBaseAddressOfPlane(image, 0);
        size_t stride = CVPixelBufferGetBytesPerRowOfPlane(image, 0);
        int frame = (int)CMTimeConvertScale(pts, 30, kCMTimeRoundingMethod_Default).value;
        for (int y=4;y<height-4;y++) for (int x=4;x<width-4;x++) {
            if (abs(x-width/2)<4 || abs(y-height/2)<4) continue;
            unsigned delta = abs((int)ybase[y*stride+x] - luma(x,y,frame));
            if (delta > maxDifference) maxDifference=delta;
        }
        CVPixelBufferUnlockBaseAddress(image, kCVPixelBufferLock_ReadOnly);
        decoded++;
        emit(@"decode-callback", @{@"status":@(status), @"frame":@(frame),
                                  @"max_luma_error":@(maxDifference)});
    }
}

static void dumpFormat(NSString *tag, CMFormatDescriptionRef desc) {
    NSDictionary *ext = (__bridge NSDictionary *)CMFormatDescriptionGetExtensions(desc);
    NSDictionary *atoms = ext[(__bridge id)kCMFormatDescriptionExtension_SampleDescriptionExtensionAtoms];
    NSData *hvcC = atoms[@"hvcC"];
    CMVideoDimensions dims = CMVideoFormatDescriptionGetDimensions(desc);
    NSMutableArray *sets = [NSMutableArray array];
    size_t count = 0; int nalLen = 0;
    CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(desc, 0, NULL, NULL, &count, &nalLen);
    for (size_t i = 0; i < count; i++) {
        const uint8_t *p = NULL; size_t n = 0;
        if (!CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(desc, i, &p, &n, NULL, NULL))
            [sets addObject:@{@"type":@((p[0] >> 1) & 0x3f), @"bytes":@(n),
                              @"hex":hex([NSData dataWithBytes:p length:n])}];
    }
    NSMutableDictionary *other = [NSMutableDictionary dictionary];
    for (id key in ext) {
        if ([key isEqual:(__bridge id)kCMFormatDescriptionExtension_SampleDescriptionExtensionAtoms]) continue;
        other[[key description]] = [ext[key] description];
    }
    emit(tag, @{@"width":@(dims.width), @"height":@(dims.height), @"nal_length_size":@(nalLen),
                @"hvcC_bytes":@(hvcC.length), @"hvcC":hvcC ? hex(hvcC) : @"",
                @"parameter_sets":sets, @"extensions":other,
                @"atom_keys":[atoms.allKeys description]});
}

// Returns create status; fills usingHardware. Decodes every sample in `list`.
static OSStatus decodeWith(NSString *tag, CMFormatDescriptionRef desc, NSArray *list,
                           BOOL require, BOOL enable, BOOL *usingHardware) {
    decoded = 0; decodeErrors = 0; maxDifference = 0;
    NSDictionary *attrs=@{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
        (__bridge id)kCVPixelBufferWidthKey:@(width), (__bridge id)kCVPixelBufferHeightKey:@(height),
        (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
    NSMutableDictionary *spec = [NSMutableDictionary dictionary];
    spec[(__bridge id)kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder] = @(enable);
    if (require) spec[(__bridge id)kVTVideoDecoderSpecification_RequireHardwareAcceleratedVideoDecoder] = @YES;
    VTDecompressionOutputCallbackRecord callback={decodedFrame,NULL};
    VTDecompressionSessionRef decoder=NULL;
    OSStatus status=VTDecompressionSessionCreate(NULL,desc,(__bridge CFDictionaryRef)spec,
        (__bridge CFDictionaryRef)attrs,&callback,&decoder);
    BOOL selected = NO; OSStatus query = -1;
    if (!status && decoder) {
        CFTypeRef using=NULL;
        query=VTSessionCopyProperty(decoder,kVTDecompressionPropertyKey_UsingHardwareAcceleratedVideoDecoder,NULL,&using);
        selected = using && CFEqual(using,kCFBooleanTrue);
        if (using) CFRelease(using);
        for (id sample in list) {
            OSStatus s=VTDecompressionSessionDecodeFrame(decoder,(__bridge CMSampleBufferRef)sample,0,NULL,NULL);
            if (s) { decodeErrors++; emit(@"decode-submit-error", @{@"tag":tag, @"status":@(s)}); }
        }
        VTDecompressionSessionWaitForAsynchronousFrames(decoder);
        VTDecompressionSessionInvalidate(decoder); CFRelease(decoder);
    }
    if (usingHardware) *usingHardware = selected;
    emit(@"decode-variant", @{@"tag":tag, @"create_status":@(status), @"query_status":@(query),
        @"using_hardware":@(selected), @"decoded":@(decoded), @"errors":@(decodeErrors),
        @"max_luma_error":@(maxDifference), @"require":@(require), @"enable":@(enable)});
    return status;
}

static NSArray *rewrap(NSArray *list, CMFormatDescriptionRef desc) {
    NSMutableArray *out = [NSMutableArray array];
    for (id s in list) {
        CMSampleBufferRef sample = (__bridge CMSampleBufferRef)s;
        CMBlockBufferRef data = CMSampleBufferGetDataBuffer(sample);
        CMSampleTimingInfo timing; CMSampleBufferGetSampleTimingInfo(sample, 0, &timing);
        size_t size = CMBlockBufferGetDataLength(data);
        CMSampleBufferRef copy = NULL;
        if (!CMSampleBufferCreateReady(NULL, data, desc, 1, 1, &timing, 1, &size, &copy) && copy)
            [out addObject:(__bridge_transfer id)copy];
    }
    return out;
}

static BOOL encodeAll(CMVideoCodecType codec, BOOL hardware, uint64_t registry) {
    NSMutableDictionary *spec = [@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(hardware)} mutableCopy];
    if (hardware) {
        spec[(__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder]=@YES;
        spec[(__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID]=@(registry);
    }
    NSDictionary *attrs=@{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
        (__bridge id)kCVPixelBufferWidthKey:@(width), (__bridge id)kCVPixelBufferHeightKey:@(height),
        (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
    VTCompressionSessionRef session=NULL;
    OSStatus status=VTCompressionSessionCreate(NULL,width,height,codec,(__bridge CFDictionaryRef)spec,
        (__bridge CFDictionaryRef)attrs,NULL,encoded,NULL,&session);
    emit(@"encoder-create", @{@"status":@(status), @"hardware_requested":@(hardware)});
    if (status || !session) return NO;
    VTSessionSetProperty(session,kVTCompressionPropertyKey_AllowFrameReordering,kCFBooleanFalse);
    status=VTCompressionSessionPrepareToEncodeFrames(session);
    if (status) { VTCompressionSessionInvalidate(session); CFRelease(session); return NO; }
    CFTypeRef encoderID=NULL, profile=NULL;
    VTSessionCopyProperty(session,kVTCompressionPropertyKey_EncoderID,NULL,&encoderID);
    VTSessionCopyProperty(session,kVTCompressionPropertyKey_ProfileLevel,NULL,&profile);
    emit(@"selected-encoder", @{@"encoder_id":encoderID ? [(__bridge id)encoderID description] : @"unknown",
                                @"profile_level":profile ? [(__bridge id)profile description] : @"unknown"});
    if (encoderID) CFRelease(encoderID); if (profile) CFRelease(profile);
    for (int frame=0;frame<frameCount;frame++) {
        CVPixelBufferRef pixel=NULL;
        if (CVPixelBufferCreate(NULL,width,height,kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                (__bridge CFDictionaryRef)attrs,&pixel)) return NO;
        CVPixelBufferLockBaseAddress(pixel,0);
        uint8_t *base=CVPixelBufferGetBaseAddressOfPlane(pixel,0);
        size_t stride=CVPixelBufferGetBytesPerRowOfPlane(pixel,0);
        for(int y=0;y<height;y++) for(int x=0;x<width;x++) base[y*stride+x]=luma(x,y,frame);
        uint8_t *uv=CVPixelBufferGetBaseAddressOfPlane(pixel,1);
        size_t uvstride=CVPixelBufferGetBytesPerRowOfPlane(pixel,1);
        for(int y=0;y<height/2;y++) memset(uv+y*uvstride,128,width);
        CVPixelBufferUnlockBaseAddress(pixel,0);
        status=VTCompressionSessionEncodeFrame(session,pixel,CMTimeMake(frame,30),CMTimeMake(1,30),NULL,NULL,NULL);
        CVPixelBufferRelease(pixel);
        if(status) return NO;
    }
    status=VTCompressionSessionCompleteFrames(session,kCMTimeInvalid);
    VTCompressionSessionInvalidate(session); CFRelease(session);
    emit(@"encode-done", @{@"status":@(status), @"samples":@(samples.count)});
    return !status && samples.count == frameCount;
}

// stream.bin: u32 hvcC length, hvcC bytes, then per sample u32 length + AVCC/HVCC framed NALs.
static BOOL writeStream(NSString *path, CMFormatDescriptionRef desc) {
    NSDictionary *ext = (__bridge NSDictionary *)CMFormatDescriptionGetExtensions(desc);
    NSData *hvcC = ext[(__bridge id)kCMFormatDescriptionExtension_SampleDescriptionExtensionAtoms][@"hvcC"];
    if (!hvcC) return NO;
    NSMutableData *out = [NSMutableData data];
    uint32_t n = (uint32_t)hvcC.length; [out appendBytes:&n length:4]; [out appendData:hvcC];
    for (id s in samples) {
        CMBlockBufferRef data = CMSampleBufferGetDataBuffer((__bridge CMSampleBufferRef)s);
        size_t size = CMBlockBufferGetDataLength(data);
        NSMutableData *bytes = [NSMutableData dataWithLength:size];
        CMBlockBufferCopyDataBytes(data, 0, size, bytes.mutableBytes);
        n = (uint32_t)size; [out appendBytes:&n length:4]; [out appendData:bytes];
    }
    return [out writeToFile:path atomically:YES];
}

static NSArray *readStream(NSString *path, CMFormatDescriptionRef *descOut) {
    NSData *in = [NSData dataWithContentsOfFile:path];
    if (!in || in.length < 4) return nil;
    const uint8_t *p = in.bytes; NSUInteger off = 0;
    uint32_t n; memcpy(&n, p, 4); off = 4;
    NSData *hvcC = [in subdataWithRange:NSMakeRange(off, n)]; off += n;
    NSDictionary *ext = @{(__bridge id)kCMFormatDescriptionExtension_SampleDescriptionExtensionAtoms:@{@"hvcC":hvcC}};
    CMFormatDescriptionRef desc = NULL;
    OSStatus s = CMVideoFormatDescriptionCreate(NULL, kCMVideoCodecType_HEVC, width, height,
                                                (__bridge CFDictionaryRef)ext, &desc);
    emit(@"stream-read", @{@"status":@(s), @"hvcC_bytes":@(hvcC.length)});
    if (s || !desc) return nil;
    NSMutableArray *list = [NSMutableArray array];
    int frame = 0;
    while (off + 4 <= in.length) {
        memcpy(&n, p + off, 4); off += 4;
        if (off + n > in.length) break;
        CMBlockBufferRef block = NULL;
        CMBlockBufferCreateWithMemoryBlock(NULL, NULL, n, NULL, NULL, 0, n, kCMBlockBufferAssureMemoryNowFlag, &block);
        CMBlockBufferReplaceDataBytes(p + off, block, 0, n);
        off += n;
        CMSampleTimingInfo timing = {CMTimeMake(1,30), CMTimeMake(frame,30), CMTimeMake(frame,30)};
        size_t size = n; CMSampleBufferRef sample = NULL;
        if (!CMSampleBufferCreateReady(NULL, block, desc, 1, 1, &timing, 1, &size, &sample) && sample)
            [list addObject:(__bridge_transfer id)sample];
        CFRelease(block);
        frame++;
    }
    *descOut = desc;
    return list;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        setbuf(stdout, NULL);
        signal(SIGALRM, expired); alarm(150);
        samples = [NSMutableArray array];
        if (argc != 4) { fprintf(stderr, "usage: probe variants|variants-hw|decodefile registryID dir\n"); return 2; }
        NSString *mode = @(argv[1]);
        uint64_t registry = strtoull(argv[2], NULL, 0);
        NSString *dir = @(argv[3]);
        NSString *streamPath = [dir stringByAppendingPathComponent:@"stream.bin"];
        if (!registry) return 2;
        BOOL hw = NO;
        if ([mode isEqualToString:@"decodefile"]) {
            CMFormatDescriptionRef desc = NULL;
            NSArray *list = readStream(streamPath, &desc);
            if (!list.count) { emit(@"result", @{@"passed":@NO, @"reason":@"stream"}); return 1; }
            dumpFormat(@"format-file", desc);
            OSStatus s = decodeWith(@"file-require-hw", desc, list, YES, YES, &hw);
            BOOL passed = !s && hw && decoded == frameCount && !decodeErrors && maxDifference <= 8;
            emit(@"result", @{@"passed":@(passed), @"decoded":@(decoded), @"max_luma_error":@(maxDifference)});
            return passed ? 0 : 1;
        }
        BOOL hardwareEncode = [mode isEqualToString:@"variants-hw"];
        if (!encodeAll(kCMVideoCodecType_HEVC, hardwareEncode, registry)) {
            emit(@"result", @{@"passed":@NO, @"reason":@"encode"}); return 1;
        }
        CMFormatDescriptionRef desc = CMSampleBufferGetFormatDescription((__bridge CMSampleBufferRef)samples[0]);
        dumpFormat(hardwareEncode ? @"format-gva" : @"format-vcp", desc);
        NSArray *list = [samples copy];
        OSStatus v1 = decodeWith(@"require-hw", desc, list, YES, YES, &hw);
        BOOL v1hw = hw;
        if (hardwareEncode) {
            BOOL passed = !v1 && v1hw && decoded == frameCount && !decodeErrors && maxDifference <= 8;
            emit(@"result", @{@"passed":@(passed)});
            return passed ? 0 : 1;
        }
        decodeWith(@"enable-hw-only", desc, list, NO, YES, &hw);
        decodeWith(@"software", desc, list, NO, NO, &hw);
        // Rebuild the format description from the parameter sets only (drops every other extension).
        size_t count = 0; int nalLen = 4;
        CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(desc, 0, NULL, NULL, &count, &nalLen);
        const uint8_t *ptrs[8] = {0}; size_t sizes[8] = {0};
        for (size_t i = 0; i < count && i < 8; i++)
            CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(desc, i, &ptrs[i], &sizes[i], NULL, NULL);
        CMFormatDescriptionRef rebuilt = NULL;
        OSStatus rs = CMVideoFormatDescriptionCreateFromHEVCParameterSets(NULL, count < 8 ? count : 8, ptrs, sizes, nalLen, NULL, &rebuilt);
        emit(@"rebuild", @{@"status":@(rs), @"sets":@(count)});
        if (!rs && rebuilt) {
            dumpFormat(@"format-rebuilt", rebuilt);
            decodeWith(@"rebuilt-require-hw", rebuilt, rewrap(list, rebuilt), YES, YES, &hw);
            CFRelease(rebuilt);
        }
        // Bare hvcC-only description for the fresh-process test.
        BOOL wrote = writeStream(streamPath, desc);
        emit(@"stream-written", @{@"ok":@(wrote), @"path":streamPath});
        emit(@"result", @{@"passed":@(v1 == 0 && v1hw), @"v1_status":@(v1), @"v1_hardware":@(v1hw)});
        return 0;
    }
}
