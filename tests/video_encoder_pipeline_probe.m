// VideoToolbox pipelining probe: does the AMD HW encoder pipeline frames
// (accepts frame i+1 before frame i's callback) or serialize them, and how
// does per-frame cost depend on content/settings. Derived from
// video_encoder_throughput_probe.m (surfaces, session, HW-required setup,
// alarm bounding, JSON style reused).
// CLI: vt_pipeline_probe CODEC WIDTH HEIGHT BITRATE FRAMES REALTIME CONTENT MAXDELAY PRIOSPEED
//   REALTIME 0|1 -> kVTCompressionPropertyKey_RealTime
//   CONTENT simple|noise -> simple: quadrant pattern; noise: xorshift fill
//   MAXDELAY -1(skip)|N>=0 -> kVTCompressionPropertyKey_MaxFrameDelayCount
//   PRIOSPEED -1(skip)|0|1 -> kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality
// Build: clang -fobjc-arc -framework VideoToolbox -framework CoreMedia \
//   -framework CoreVideo -framework IOSurface -framework Foundation \
//   tests/video_encoder_pipeline_probe.m -o /var/tmp/vt_pipeline_probe
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <IOSurface/IOSurface.h>
extern const CFStringRef kVTCompressionPropertyKey_Priority __attribute__((weak_import));
extern const CFStringRef kVTCompressionPropertyKey_LowLatencyMode __attribute__((weak_import));
extern const CFStringRef kVTLowLatencyMode_Auto __attribute__((weak_import));
extern const CFStringRef kVTLowLatencyMode_Low __attribute__((weak_import));
extern const CFStringRef kVTLowLatencyMode_Medium __attribute__((weak_import));
extern const CFStringRef kVTLowLatencyMode_Minimum __attribute__((weak_import));
#include <stdint.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

static volatile uint64_t callbackCount, callbackBytes, callbackErrors, completedCount;
static volatile sig_atomic_t deadlineHit;
static double *gDone;
static int gFrameCount;

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

// Output callback must be cheap: atomic bookkeeping only, no locking or I/O.
static void encoded(void *outputCallbackRefCon, void *sourceFrameRefCon, OSStatus status,
                    VTEncodeInfoFlags infoFlags, CMSampleBufferRef sampleBuffer) {
    (void)outputCallbackRefCon; (void)infoFlags;
    __sync_fetch_and_add(&callbackCount, 1);
    if (status || !sampleBuffer || !CMSampleBufferDataIsReady(sampleBuffer)) {
        __sync_fetch_and_add(&callbackErrors, 1);
    } else {
        __sync_fetch_and_add(&callbackBytes, CMSampleBufferGetTotalSampleSize(sampleBuffer));
    }
    if (sourceFrameRefCon) {
        intptr_t idx = (intptr_t)sourceFrameRefCon - 1;
        if (idx >= 0 && idx < gFrameCount && gDone) {
            gDone[idx] = monotonicSeconds();
            __sync_fetch_and_add(&completedCount, 1);
        }
    }
}

static BOOL fillSimple(CVPixelBufferRef pixel, int width, int height, int frame) {
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

static uint32_t xorshift32(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return *state = x;
}

// Each of the 6 surfaces gets one distinct pseudo-random fill so successive
// frames (rotating through the surfaces) differ and are hard to compress.
static BOOL fillNoise(CVPixelBufferRef pixel, int width, int height, int seed) {
    if (CVPixelBufferLockBaseAddress(pixel, 0) != kCVReturnSuccess) return NO;
    uint8_t *y = CVPixelBufferGetBaseAddressOfPlane(pixel, 0);
    uint8_t *uv = CVPixelBufferGetBaseAddressOfPlane(pixel, 1);
    size_t ys = CVPixelBufferGetBytesPerRowOfPlane(pixel, 0);
    size_t uvs = CVPixelBufferGetBytesPerRowOfPlane(pixel, 1);
    uint32_t state = (uint32_t)(seed * 2654435761u + 1);
    if (!state) state = 0x9e3779b9u;
    for (int row = 0; row < height; ++row) {
        uint32_t r = 0;
        for (int col = 0; col < width; ++col) {
            if (!(col & 3)) r = xorshift32(&state);
            y[row * ys + col] = (uint8_t)(r >> ((col & 3) * 8));
        }
    }
    for (int row = 0; row < height / 2; ++row) {
        uint32_t r = 0;
        for (int col = 0; col < width; ++col) {
            if (!(col & 3)) r = xorshift32(&state);
            uv[row * uvs + col] = (uint8_t)(r >> ((col & 3) * 8));
        }
    }
    CVPixelBufferUnlockBaseAddress(pixel, 0);
    return YES;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        signal(SIGALRM, deadline); alarm(90);
        if (argc != 10) {
            fprintf(stderr, "usage: vt_pipeline_probe h264|hevc width height bitrate frames "
                            "0|1 simple|noise maxdelay(-1|N) priospeed(-1|0|1)\n");
            return 2;
        }
        const char *codecArg = argv[1];
        const int width = atoi(argv[2]), height = atoi(argv[3]);
        const int bitrate = atoi(argv[4]), frames = atoi(argv[5]);
        const int realtimeArg = atoi(argv[6]);
        const char *contentArg = argv[7];
        int maxDelay = atoi(argv[8]), prioSpeed = atoi(argv[9]);
        const BOOL isH264 = !strcmp(codecArg, "h264"), isHevc = !strcmp(codecArg, "hevc");
        const BOOL noiseContent = !strcmp(contentArg, "noise");
        if ((!isH264 && !isHevc) || width <= 0 || height <= 0 || bitrate <= 0 || frames <= 0 ||
            (realtimeArg != 0 && realtimeArg != 1) ||
            (!noiseContent && strcmp(contentArg, "simple")) ||
            maxDelay < -1 || prioSpeed < -1 || prioSpeed > 1) {
            fprintf(stderr, "usage: vt_pipeline_probe h264|hevc width height bitrate frames "
                            "0|1 simple|noise maxdelay(-1|N) priospeed(-1|0|1)\n");
            return 2;
        }
        const CMVideoCodecType codec = isHevc ? kCMVideoCodecType_HEVC : kCMVideoCodecType_H264;
        NSDictionary *attrs = @{(__bridge id)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),
            (__bridge id)kCVPixelBufferWidthKey:@(width), (__bridge id)kCVPixelBufferHeightKey:@(height),
            (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        NSDictionary *spec = @{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@YES,
            (__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder:@YES};

        VTCompressionSessionRef session = NULL;
        OSStatus createStatus = VTCompressionSessionCreate(NULL, width, height, codec,
            (__bridge CFDictionaryRef)spec, (__bridge CFDictionaryRef)attrs, NULL, encoded, NULL, &session);
        OSStatus configStatus = noErr;
        BOOL actualHardware = NO;
        if (!createStatus && session) {
            configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_RealTime,
                realtimeArg ? kCFBooleanTrue : kCFBooleanFalse);
            if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse);
            if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_ExpectedFrameRate, (__bridge CFTypeRef)@60);
            if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_MaxKeyFrameInterval, (__bridge CFTypeRef)@120);
            if (!configStatus) configStatus = VTSessionSetProperty(session, kVTCompressionPropertyKey_AverageBitRate, (__bridge CFTypeRef)@(bitrate));
            if (!configStatus && maxDelay >= 0) {
                OSStatus s = VTSessionSetProperty(session, kVTCompressionPropertyKey_MaxFrameDelayCount, (__bridge CFTypeRef)@(maxDelay));
                if (s) { fprintf(stdout, "UNSUPPORTED MaxFrameDelayCount %d\n", (int)s); maxDelay = -2; }
            }
            if (!configStatus && prioSpeed >= 0) {
                OSStatus s = VTSessionSetProperty(session, kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality,
                    prioSpeed ? kCFBooleanTrue : kCFBooleanFalse);
            
                if (s) { fprintf(stdout, "UNSUPPORTED PrioritizeEncodingSpeedOverQuality %d\n", (int)s); prioSpeed = -2; }
            }
            // Optional private/newer keys for encoder-preset experiments (non-fatal).
            const char *envPriority = getenv("VT_PRIORITY");
            if (!configStatus && envPriority) {
                OSStatus s = VTSessionSetProperty(session, kVTCompressionPropertyKey_Priority,
                                                  (__bridge CFTypeRef)@(atoi(envPriority)));
                fprintf(stdout, "SET Priority=%d status=%d\n", atoi(envPriority), (int)s);
            }
            const char *envLowLatency = getenv("VT_LOWLATENCY");
            if (!configStatus && envLowLatency) {
                CFStringRef mode = !strcmp(envLowLatency, "minimum") ? kVTLowLatencyMode_Minimum :
                                   !strcmp(envLowLatency, "low") ? kVTLowLatencyMode_Low :
                                   !strcmp(envLowLatency, "medium") ? kVTLowLatencyMode_Medium : kVTLowLatencyMode_Auto;
                OSStatus s = VTSessionSetProperty(session, kVTCompressionPropertyKey_LowLatencyMode, mode);
                fprintf(stdout, "SET LowLatencyMode=%s status=%d\n", envLowLatency, (int)s);
            }
            if (!configStatus) configStatus = VTCompressionSessionPrepareToEncodeFrames(session);
            CFTypeRef actual = NULL;
            VTSessionCopyProperty(session, kVTCompressionPropertyKey_UsingHardwareAcceleratedVideoEncoder, NULL, &actual);
            actualHardware = actual && CFEqual(actual, kCFBooleanTrue);
            if (actual) CFRelease(actual);
        }
        if (createStatus || !session || configStatus || !actualHardware) {
            printf("{\"status\":\"error\",\"passed\":false,\"codec\":\"%s\",\"width\":%d,\"height\":%d,"
                   "\"bitrate\":%d,\"frames\":%d,\"realtime\":%d,\"content\":\"%s\",\"maxdelay\":%d,"
                   "\"priospeed\":%d,\"create_status\":%d,\"config_status\":%d,\"actual_hardware\":%s}\n",
                   codecArg, width, height, bitrate, frames, realtimeArg, contentArg, maxDelay, prioSpeed,
                   createStatus, configStatus, actualHardware ? "true" : "false");
            if (session) { VTCompressionSessionInvalidate(session); CFRelease(session); }
            return 1;
        }

        CVPixelBufferRef surfaces[6] = {};
        OSStatus surfaceStatus = noErr;
        for (int i = 0; i < 6 && !surfaceStatus; ++i) {
            surfaceStatus = CVPixelBufferCreate(NULL, width, height, kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                                                 (__bridge CFDictionaryRef)attrs, &surfaces[i]);
            BOOL filled = noiseContent ? fillNoise(surfaces[i], width, height, i) : fillSimple(surfaces[i], width, height, i);
            if (!surfaceStatus && !filled) surfaceStatus = kCVReturnError;
        }

        OSStatus warmupStatus = surfaceStatus;
        for (int i = 0; i < 12 && !warmupStatus; ++i)
            warmupStatus = VTCompressionSessionEncodeFrame(session, surfaces[i % 6], CMTimeMake(i, 60), kCMTimeInvalid, NULL, NULL, NULL);
        if (!warmupStatus) warmupStatus = VTCompressionSessionCompleteFrames(session, kCMTimeInvalid);
        if (!warmupStatus && (callbackCount != 12 || callbackErrors)) warmupStatus = -1;

        callbackCount = callbackBytes = callbackErrors = completedCount = 0;
        gFrameCount = frames;
        double *tSubmitStart = calloc((size_t)frames, sizeof(double));
        double *tSubmitEnd = calloc((size_t)frames, sizeof(double));
        gDone = calloc((size_t)frames, sizeof(double));
        for (int i = 0; i < frames; ++i) gDone[i] = -1.0;

        uint64_t submitErrors = 0, inflightMax = 0, inflightGe2 = 0;
        for (int i = 0; i < frames && !warmupStatus; ++i) {
            uint64_t completedNow = completedCount;
            uint64_t inflight = (uint64_t)i - completedNow;
            if (inflight > inflightMax) inflightMax = inflight;
            if (inflight >= 2) ++inflightGe2;
            tSubmitStart[i] = monotonicSeconds();
            OSStatus status = VTCompressionSessionEncodeFrame(session, surfaces[i % 6], CMTimeMake(i + 12, 60),
                kCMTimeInvalid, NULL, (void *)(intptr_t)(i + 1), NULL);
            tSubmitEnd[i] = monotonicSeconds();
            if (status) ++submitErrors;
            if (deadlineHit) break;
        }
        OSStatus flushStatus = warmupStatus ? warmupStatus : VTCompressionSessionCompleteFrames(session, kCMTimeInvalid);

        for (int i = 0; i < 6; ++i) if (surfaces[i]) CVPixelBufferRelease(surfaces[i]);
        VTCompressionSessionInvalidate(session); CFRelease(session); alarm(0);

        double sumCall = 0, maxCall = 0, sumLat = 0, minLat = 1e18, maxLat = 0;
        int latCount = 0;
        for (int i = 0; i < frames; ++i) {
            double callMs = (tSubmitEnd[i] - tSubmitStart[i]) * 1000.0;
            sumCall += callMs; if (callMs > maxCall) maxCall = callMs;
            if (gDone[i] >= 0) {
                double latMs = (gDone[i] - tSubmitStart[i]) * 1000.0;
                sumLat += latMs; ++latCount;
                if (latMs < minLat) minLat = latMs;
                if (latMs > maxLat) maxLat = latMs;
            }
        }
        double encodeCallMeanMs = frames ? sumCall / frames : 0;
        double latencyMeanMs = latCount ? sumLat / latCount : 0;
        if (!latCount) minLat = 0;
        double lastDone = gDone[frames - 1], firstStart = tSubmitStart[0];
        double throughputFps = (lastDone >= 0 && lastDone > firstStart) ? frames / (lastDone - firstStart) : 0;
        double meanBytesPerFrame = callbackCount ? (double)callbackBytes / (double)callbackCount : 0;
        BOOL passed = !createStatus && !configStatus && !warmupStatus && !flushStatus && actualHardware &&
                      !submitErrors && !callbackErrors && callbackCount == (uint64_t)frames && latCount == frames;

        printf("CODEC %s\nWIDTH %d\nHEIGHT %d\nBITRATE %d\nFRAMES %d\nREALTIME %d\nCONTENT %s\n"
               "MAXDELAY %d\nPRIOSPEED %d\nACTUAL_HARDWARE %s\nCREATE_STATUS %d\nCONFIG_STATUS %d\n"
               "WARMUP_STATUS %d\nFLUSH_STATUS %d\nCALLBACKS %llu\nCALLBACK_ERRORS %llu\n"
               "SUBMISSION_ERRORS %llu\nTOTAL_BYTES %llu\nMEAN_BYTES_PER_FRAME %.3f\n"
               "ENCODE_CALL_MS_MEAN %.6f\nENCODE_CALL_MS_MAX %.6f\nLATENCY_MS_MEAN %.6f\n"
               "LATENCY_MS_MIN %.6f\nLATENCY_MS_MAX %.6f\nTHROUGHPUT_FPS %.6f\n"
               "INFLIGHT_MAX %llu\nINFLIGHT_GE2_COUNT %llu\nPASSED %s\n",
               codecArg, width, height, bitrate, frames, realtimeArg, contentArg, maxDelay, prioSpeed,
               actualHardware ? "true" : "false", createStatus, configStatus, warmupStatus, flushStatus,
               (unsigned long long)callbackCount, (unsigned long long)callbackErrors,
               (unsigned long long)submitErrors, (unsigned long long)callbackBytes, meanBytesPerFrame,
               encodeCallMeanMs, maxCall, latencyMeanMs, minLat, maxLat, throughputFps,
               (unsigned long long)inflightMax, (unsigned long long)inflightGe2, passed ? "true" : "false");

        printf("{\"status\":\"result\",\"passed\":%s,\"codec\":\"%s\",\"width\":%d,\"height\":%d,"
               "\"bitrate\":%d,\"frames\":%d,\"realtime\":%d,\"content\":\"%s\",\"maxdelay\":%d,"
               "\"priospeed\":%d,\"actual_hardware\":%s,\"create_status\":%d,\"config_status\":%d,"
               "\"warmup_status\":%d,\"flush_status\":%d,\"callbacks\":%llu,\"callback_errors\":%llu,"
               "\"submission_errors\":%llu,\"total_bytes\":%llu,\"mean_bytes_per_frame\":%.3f,"
               "\"encode_call_ms_mean\":%.6f,\"encode_call_ms_max\":%.6f,\"latency_ms_mean\":%.6f,"
               "\"latency_ms_min\":%.6f,\"latency_ms_max\":%.6f,\"throughput_fps\":%.6f,"
               "\"inflight_max\":%llu,\"inflight_ge2_count\":%llu}\n",
               passed ? "true" : "false", codecArg, width, height, bitrate, frames, realtimeArg, contentArg,
               maxDelay, prioSpeed, actualHardware ? "true" : "false", createStatus, configStatus,
               warmupStatus, flushStatus, (unsigned long long)callbackCount,
               (unsigned long long)callbackErrors, (unsigned long long)submitErrors,
               (unsigned long long)callbackBytes, meanBytesPerFrame, encodeCallMeanMs, maxCall,
               latencyMeanMs, minLat, maxLat, throughputFps, (unsigned long long)inflightMax,
               (unsigned long long)inflightGe2);

        free(tSubmitStart); free(tSubmitEnd); free(gDone); gDone = NULL;
        return passed ? 0 : 1;
    }
}
