// Encoder-only throughput probe. No capture, display, or decoder path is used.
// CLI: probe h264|hevc hw|sw registryID width height frames bitrate [pool|fresh]
// Build: clang -fobjc-arc video_encoder_throughput_probe.m -framework Foundation \
//        -framework VideoToolbox -framework CoreMedia -framework CoreVideo -o probe
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile uint64_t callbackCount, callbackBytes, callbackErrors;
static volatile sig_atomic_t deadlineHit;

static double monotonicSeconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static void deadline(int signalNumber) {
    (void)signalNumber;
    deadlineHit = 1;
    const char json[] = "{\"status\":\"deadline\",\"passed\":false}\n";
    write(STDOUT_FILENO, json, sizeof(json) - 1);
    _exit(124);
}

static void encoded(void *context, void *source, OSStatus status,
                    VTEncodeInfoFlags flags, CMSampleBufferRef sample) {
    (void)context; (void)source; (void)flags;
    __sync_fetch_and_add(&callbackCount, 1);
    if (status || !sample || !CMSampleBufferDataIsReady(sample))
        __sync_fetch_and_add(&callbackErrors, 1);
    else
        __sync_fetch_and_add(&callbackBytes, CMSampleBufferGetTotalSampleSize(sample));
}

static BOOL fillSurface(CVPixelBufferRef pixel, int width, int height, int frame) {
    if (CVPixelBufferLockBaseAddress(pixel, 0) != kCVReturnSuccess) return NO;
    uint8_t *y = CVPixelBufferGetBaseAddressOfPlane(pixel, 0);
    uint8_t *uv = CVPixelBufferGetBaseAddressOfPlane(pixel, 1);
    size_t ys = CVPixelBufferGetBytesPerRowOfPlane(pixel, 0);
    size_t uvs = CVPixelBufferGetBytesPerRowOfPlane(pixel, 1);
    for (int row = 0; row < height; ++row)
        for (int col = 0; col < width; ++col)
            y[row * ys + col] = (uint8_t)(32 + ((col >= width / 2) ? 80 : 0) +
                                           ((row >= height / 2) ? 80 : 0) + frame);
    for (int row = 0; row < height / 2; ++row)
        memset(uv + row * uvs, 128, width);
    CVPixelBufferUnlockBaseAddress(pixel, 0);
    return YES;
}

static BOOL copySurface(CVPixelBufferRef destination, CVPixelBufferRef source,
                        int width, int height) {
    if (CVPixelBufferLockBaseAddress(source, kCVPixelBufferLock_ReadOnly) != kCVReturnSuccess)
        return NO;
    if (CVPixelBufferLockBaseAddress(destination, 0) != kCVReturnSuccess) {
        CVPixelBufferUnlockBaseAddress(source, kCVPixelBufferLock_ReadOnly);
        return NO;
    }
    for (size_t plane = 0; plane < 2; ++plane) {
        const uint8_t *src = CVPixelBufferGetBaseAddressOfPlane(source, plane);
        uint8_t *dst = CVPixelBufferGetBaseAddressOfPlane(destination, plane);
        const size_t srcStride = CVPixelBufferGetBytesPerRowOfPlane(source, plane);
        const size_t dstStride = CVPixelBufferGetBytesPerRowOfPlane(destination, plane);
        const size_t rows = plane == 0 ? (size_t)height : (size_t)height / 2;
        const size_t rowBytes = plane == 0 ? (size_t)width : (size_t)width;
        for (size_t row = 0; row < rows; ++row)
            memcpy(dst + row * dstStride, src + row * srcStride, rowBytes);
    }
    CVPixelBufferUnlockBaseAddress(destination, 0);
    CVPixelBufferUnlockBaseAddress(source, kCVPixelBufferLock_ReadOnly);
    return YES;
}

static void emitResult(const char *codec, const char *mode, uint64_t registry,
                       int width, int height, int frames, int bitrate,
                       const char *bufferMode,
                       BOOL actualHardware, OSStatus createStatus, OSStatus configStatus,
                       OSStatus warmupStatus, OSStatus flushStatus, double elapsed,
                       uint64_t submissions, uint64_t submitErrors, double submitTotal,
                       double submitMax, double preparationTotal) {
    printf("{\"status\":\"result\",\"passed\":%s,\"codec\":\"%s\",\"requested_mode\":\"%s\","
           "\"registry_id\":%llu,\"width\":%d,\"height\":%d,\"frames\":%d,\"bitrate\":%d,\"mode\":\"%s\","
           "\"actual_hardware\":%s,\"create_status\":%d,\"config_status\":%d,"
           "\"warmup_status\":%d,\"flush_status\":%d,\"elapsed_seconds\":%.9f,"
           "\"fps\":%.6f,\"callbacks\":%llu,\"bytes\":%llu,\"callback_errors\":%llu,"
           "\"submission_count\":%llu,\"submission_errors\":%llu,\"submission_total_seconds\":%.9f,"
           "\"submission_max_seconds\":%.9f,\"pixel_preparation_total_seconds\":%.9f,"
           "\"non_preparation_elapsed_seconds\":%.9f}\n",
           (createStatus == noErr && configStatus == noErr && warmupStatus == noErr &&
            flushStatus == noErr && !submitErrors && !callbackErrors &&
            callbackCount == (uint64_t)frames && (actualHardware == (mode[0] == 'h'))) ? "true" : "false",
           codec, mode, (unsigned long long)registry, width, height, frames, bitrate,
           bufferMode,
           actualHardware ? "true" : "false", createStatus, configStatus, warmupStatus,
           flushStatus, elapsed, elapsed > 0 ? frames / elapsed : 0,
           (unsigned long long)callbackCount, (unsigned long long)callbackBytes,
           (unsigned long long)callbackErrors, (unsigned long long)submissions,
           (unsigned long long)submitErrors, submitTotal, submitMax, preparationTotal,
           // This is wall time minus measured CPU preparation; it is not GPU-only time.
           elapsed > preparationTotal ? elapsed - preparationTotal : 0);
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        signal(SIGALRM, deadline); alarm(60);
        if ((argc != 8 && argc != 9) || (strcmp(argv[1], "h264") && strcmp(argv[1], "hevc")) ||
            (strcmp(argv[2], "hw") && strcmp(argv[2], "sw"))) {
            fprintf(stderr, "usage: probe h264|hevc hw|sw registryID width height frames bitrate [pool|fresh]\n");
            return 2;
        }
        const BOOL requestHardware = !strcmp(argv[2], "hw");
        const uint64_t registry = strtoull(argv[3], NULL, 0);
        const int width = atoi(argv[4]), height = atoi(argv[5]);
        const int frames = atoi(argv[6]), bitrate = atoi(argv[7]);
        const BOOL fresh = argc == 9 && !strcmp(argv[8], "fresh");
        const BOOL poolMode = argc == 9 && !strcmp(argv[8], "pool");
        if (argc == 9 && !fresh && !poolMode) return 2;
        const char *bufferMode = fresh ? "fresh" : (poolMode ? "pool" : "reused");
        if (width < 64 || width > 3840 || height < 64 || height > 2160 ||
            (width & 1) || (height & 1) || frames < 1 || frames > 240 || bitrate < 1 ||
            (requestHardware && !registry)) return 2;
        const CMVideoCodecType codec = !strcmp(argv[1], "hevc") ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264;
        NSDictionary *attrs = @{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
            (__bridge id)kCVPixelBufferWidthKey:@(width), (__bridge id)kCVPixelBufferHeightKey:@(height),
            (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        NSMutableDictionary *spec = [@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@(requestHardware)} mutableCopy];
        if (requestHardware) {
            spec[(__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder] = @YES;
            spec[(__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID] = @(registry);
        }
        VTCompressionSessionRef session = NULL;
        OSStatus createStatus = VTCompressionSessionCreate(NULL, width, height, codec,
            (__bridge CFDictionaryRef)spec, (__bridge CFDictionaryRef)attrs, NULL, encoded, NULL, &session);
        if (createStatus || !session) {
            emitResult(argv[1], argv[2], registry, width, height, frames, bitrate, bufferMode, NO,
                       createStatus, -1, -1, -1, 0, 0, 0, 0, 0, 0);
            return 1;
        }
        OSStatus configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_RealTime, kCFBooleanTrue);
        if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse);
        if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_ExpectedFrameRate, (__bridge CFTypeRef)@60);
        if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_MaxKeyFrameInterval, (__bridge CFTypeRef)@120);
        if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_AverageBitRate, (__bridge CFTypeRef)@(bitrate));
        OSStatus prepareStatus = configStatus ? configStatus : VTCompressionSessionPrepareToEncodeFrames(session);
        CFTypeRef actual = NULL;
        VTSessionCopyProperty(session, kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder, NULL, &actual);
        const BOOL actualHardware = actual && CFEqual(actual, kCFBooleanTrue);
        if (actual) CFRelease(actual);
        CVPixelBufferRef surfaces[6] = {};
        OSStatus surfaceStatus = noErr;
        for (int i = 0; i < 6 && !surfaceStatus; ++i) {
            surfaceStatus = CVPixelBufferCreate(NULL, width, height, kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                                                 (__bridge CFDictionaryRef)attrs, &surfaces[i]);
            if (!surfaceStatus && !fillSurface(surfaces[i], width, height, i)) surfaceStatus = kCVReturnError;
        }
        CVPixelBufferPoolRef pool = NULL;
        if (!surfaceStatus && poolMode) {
            NSDictionary *poolAttrs = @{(__bridge id)kCVPixelBufferPoolMinimumBufferCountKey:@6};
            surfaceStatus = CVPixelBufferPoolCreate(NULL, (__bridge CFDictionaryRef)poolAttrs,
                (__bridge CFDictionaryRef)attrs, &pool);
        }
        OSStatus warmupStatus = prepareStatus ? prepareStatus : surfaceStatus;
        for (int i = 0; i < 12 && !warmupStatus; ++i)
            warmupStatus = VTCompressionSessionEncodeFrame(session, surfaces[i % 6], CMTimeMake(i, 60), kCMTimeInvalid, NULL, NULL, NULL);
        if (!warmupStatus) warmupStatus = VTCompressionSessionCompleteFrames(session, kCMTimeInvalid);
        if (!warmupStatus && (callbackCount != 12 || callbackErrors)) warmupStatus = -1;
        callbackCount = callbackBytes = callbackErrors = 0;
        uint64_t submissions = 0, submitErrors = 0;
        double submitTotal = 0, submitMax = 0, preparationTotal = 0;
        double start = monotonicSeconds();
        for (int i = 0; i < frames && !warmupStatus; ++i) {
            CVPixelBufferRef current = surfaces[i % 6];
            if (fresh || poolMode) {
                double prepareStart = monotonicSeconds();
                current = NULL;
                OSStatus create = poolMode
                    ? CVPixelBufferPoolCreatePixelBuffer(NULL, pool, &current)
                    : CVPixelBufferCreate(NULL, width, height,
                        kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                        (__bridge CFDictionaryRef)attrs, &current);
                if (!create && !copySurface(current, surfaces[i % 6], width, height))
                    create = kCVReturnError;
                preparationTotal += monotonicSeconds() - prepareStart;
                if (create) { ++submitErrors; if (current) CVPixelBufferRelease(current); break; }
            }
            double before = monotonicSeconds();
            OSStatus status = VTCompressionSessionEncodeFrame(session, current, CMTimeMake(i + 12, 60), kCMTimeInvalid, NULL, NULL, NULL);
            double duration = monotonicSeconds() - before;
            submitTotal += duration; if (duration > submitMax) submitMax = duration;
            ++submissions; if (status) ++submitErrors;
            if (fresh || poolMode) CVPixelBufferRelease(current);
            if (deadlineHit) break;
        }
        OSStatus flushStatus = warmupStatus ? warmupStatus : VTCompressionSessionCompleteFrames(session, kCMTimeInvalid);
        double elapsed = monotonicSeconds() - start;
        for (int i = 0; i < 6; ++i) if (surfaces[i]) CVPixelBufferRelease(surfaces[i]);
        if (pool) CVPixelBufferPoolRelease(pool);
        VTCompressionSessionInvalidate(session); CFRelease(session); alarm(0);
        emitResult(argv[1], argv[2], registry, width, height, frames, bitrate, bufferMode, actualHardware,
                   createStatus, configStatus, warmupStatus, flushStatus, elapsed,
                   submissions, submitErrors, submitTotal, submitMax, preparationTotal);
        return (createStatus == noErr && configStatus == noErr && warmupStatus == noErr &&
                flushStatus == noErr && !submitErrors && !callbackErrors &&
                callbackCount == (uint64_t)frames && (actualHardware == requestHardware)) ? 0 : 1;
    }
}
