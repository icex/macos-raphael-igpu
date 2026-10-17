// GPU clock/bandwidth micro-benchmark for the AMD Raphael iGPU (RDNA2, 2 CUs, 128 FP32
// lanes, nominal max 2200 MHz, 563 GFLOPS FMA peak). Estimates effective core clock from
// a latency-hiding FLOPS kernel, memory bandwidth from a blit and a compute copy, NV12
// conversion cost for a 4K frame, and short-kernel submission latency. Shaders are
// compiled at runtime via newLibraryWithSource:options:error: (no .metallib). Headless,
// no window, no app bundle. API surface stays at macOS 10.15-12 level.
// Build: clang -fobjc-arc -framework Metal -framework Foundation -framework QuartzCore \
//        tests/gpu_clock_probe.m -o /var/tmp/gpu_clock_probe
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static void deadline(int signalNumber) {
    (void)signalNumber;
    const char msg[] = "{\"status\":\"deadline\",\"passed\":false}\n";
    write(STDOUT_FILENO, msg, sizeof(msg) - 1);
    _exit(124);
}

static void fail(NSString *reason) {
    fprintf(stderr, "GPU_CLOCK_PROBE_ERROR %s\n", reason.UTF8String);
    printf("{\"status\":\"error\",\"passed\":false,\"message\":\"%s\"}\n", reason.UTF8String);
    exit(1);
}

static double monotonicSeconds(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static int compareDouble(const void *a, const void *b) {
    double da = *(const double *)a, db = *(const double *)b;
    return (da > db) - (da < db);
}

static double median(double *values, int count) {
    double copy[32];
    for (int i = 0; i < count; ++i) copy[i] = values[i];
    qsort(copy, (size_t)count, sizeof(double), compareDouble);
    return count & 1 ? copy[count / 2] : (copy[count / 2 - 1] + copy[count / 2]) / 2.0;
}

static double minOf(double *values, int count) {
    double m = values[0];
    for (int i = 1; i < count; ++i) if (values[i] < m) m = values[i];
    return m;
}

static double meanOf(double *values, int count) {
    double s = 0; for (int i = 0; i < count; ++i) s += values[i];
    return s / count;
}

// Converts a series of elapsed-time samples into a throughput rate (numerator/seconds):
// best from the fastest sample, median from the per-sample rate distribution.
static void throughputStats(double numerator, double *seconds, int count, double *best, double *med) {
    double rate[32];
    for (int i = 0; i < count; ++i) rate[i] = seconds[i] > 0 ? numerator / seconds[i] : 0;
    *best = numerator / minOf(seconds, count);
    *med = median(rate, count);
}

static double clockMHzFromGFLOPS(double gflops) {
    return gflops * 1e9 / (128.0 * 2.0) / 1e6;
}

// Long dependent fma() chain on float4 to hide instruction/memory latency behind ALU
// work: 8 independent accumulators, each carrying a serial dependency across iterations,
// so the compiler cannot fold the loop and the GPU cannot retire faster than its real
// FMA throughput allows. 2 flops per fma (multiply + add) per float4 lane component.
static NSString *const kFlopsSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "kernel void flops_chain(device float4 *out [[buffer(0)]],\n"
     "                        constant uint &iterations [[buffer(1)]],\n"
     "                        uint tid [[thread_position_in_grid]]) {\n"
     "  float4 a0 = float4(tid & 15u) * 1e-4f + 1.0f;\n"
     "  float4 a1 = a0 + 0.5f, a2 = a0 + 1.0f, a3 = a0 + 1.5f;\n"
     "  float4 a4 = a0 + 2.0f, a5 = a0 + 2.5f, a6 = a0 + 3.0f, a7 = a0 + 3.5f;\n"
     "  float4 m = float4(1.0000001f);\n"
     "  for (uint i = 0; i < iterations; ++i) {\n"
     "    a0 = fma(a0, m, a1); a1 = fma(a1, m, a2); a2 = fma(a2, m, a3); a3 = fma(a3, m, a4);\n"
     "    a4 = fma(a4, m, a5); a5 = fma(a5, m, a6); a6 = fma(a6, m, a7); a7 = fma(a7, m, a0);\n"
     "  }\n"
     "  out[tid] = a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7;\n"
     "}\n";

// float4 load/store copy kernel, compared against the blit-engine copy for the same
// buffers so ALU-path and DMA-path bandwidth can be told apart.
static NSString *const kCopySource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "kernel void copy_f4(device float4 *dst [[buffer(0)]], device const float4 *src [[buffer(1)]],\n"
     "                    uint tid [[thread_position_in_grid]]) { dst[tid] = src[tid]; }\n";

// RGBA8 -> NV12 (Y r8 plane + interleaved UV rg8 plane, 4:2:0), BT.601-ish coefficients.
static NSString *const kConvertSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "kernel void rgba_to_nv12(texture2d<float, access::read> rgba [[texture(0)]],\n"
     "                        texture2d<float, access::write> yPlane [[texture(1)]],\n"
     "                        texture2d<float, access::write> uvPlane [[texture(2)]],\n"
     "                        uint2 gid [[thread_position_in_grid]]) {\n"
     "  if (gid.x * 2 >= rgba.get_width() || gid.y * 2 >= rgba.get_height()) return;\n"
     "  float3 acc = float3(0);\n"
     "  uint2 origin = gid * 2;\n"
     "  for (uint dy = 0; dy < 2; ++dy)\n"
     "    for (uint dx = 0; dx < 2; ++dx) {\n"
     "      float4 c = rgba.read(origin + uint2(dx, dy));\n"
     "      yPlane.write(float4(0.299f * c.r + 0.587f * c.g + 0.114f * c.b, 0, 0, 1), origin + uint2(dx, dy));\n"
     "      acc += c.rgb;\n"
     "    }\n"
     "  acc *= 0.25f;\n"
     "  float u = -0.169f * acc.r - 0.331f * acc.g + 0.5f * acc.b + 0.5f;\n"
     "  float v = 0.5f * acc.r - 0.419f * acc.g - 0.081f * acc.b + 0.5f;\n"
     "  uvPlane.write(float4(u, v, 0, 1), gid);\n"
     "}\n";

static NSString *const kTrivialSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "kernel void trivial(device uint *out [[buffer(0)]]) { out[0] = out[0] + 1; }\n";

static id<MTLLibrary> compileLibrary(id<MTLDevice> device, NSString *source, NSString *label) {
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    if (!library) fail([NSString stringWithFormat:@"library compile failed (%@): %@", label,
                         error.localizedDescription ?: @"unknown"]);
    return library;
}

static id<MTLComputePipelineState> makePipeline(id<MTLDevice> device, id<MTLLibrary> library, NSString *function) {
    NSError *error = nil;
    id<MTLFunction> fn = [library newFunctionWithName:function];
    if (!fn) fail([NSString stringWithFormat:@"missing function %@", function]);
    id<MTLComputePipelineState> pipeline = [device newComputePipelineStateWithFunction:fn error:&error];
    if (!pipeline) fail([NSString stringWithFormat:@"pipeline failed (%@): %@", function,
                         error.localizedDescription ?: @"unknown"]);
    return pipeline;
}

// Runs one command buffer, waits for it, and returns wall-clock plus GPU-reported
// seconds (GPUStartTime/GPUEndTime, available since macOS 10.15; zero on older systems).
static void runOnce(id<MTLCommandQueue> queue, void (^encode)(id<MTLCommandBuffer>),
                    double *wallSeconds, double *gpuSeconds) {
    id<MTLCommandBuffer> command = [queue commandBuffer];
    encode(command);
    double start = monotonicSeconds();
    [command commit];
    [command waitUntilCompleted];
    *wallSeconds = monotonicSeconds() - start;
    if (command.error) fail([NSString stringWithFormat:@"command buffer error: %@",
                             command.error.localizedDescription ?: @"unknown"]);
    double gpu = command.GPUEndTime - command.GPUStartTime;
    *gpuSeconds = gpu > 0 ? gpu : 0;
}

int main(int argc, const char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        signal(SIGALRM, deadline);
        alarm(120);

        NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
        if (devices.count == 0) fail(@"MTLCopyAllDevices returned no devices");
        printf("DEVICE_COUNT %lu\n", (unsigned long)devices.count);
        id<MTLDevice> device = nil;
        for (id<MTLDevice> d in devices) {
            printf("DEVICE name=\"%s\" registryID=%llu isLowPower=%d isHeadless=%d\n",
                   d.name.UTF8String, (unsigned long long)d.registryID, (int)d.isLowPower, (int)d.isHeadless);
            if (!device && ([d.name rangeOfString:@"AMD"].location != NSNotFound ||
                            [d.name rangeOfString:@"Radeon"].location != NSNotFound))
                device = d;
        }
        if (!device) device = devices[0];
        printf("CHOSEN_DEVICE name=\"%s\" registryID=%llu\n", device.name.UTF8String,
               (unsigned long long)device.registryID);

        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!queue) fail(@"newCommandQueue failed");

        // ---- Test 1: FLOPS ----
        id<MTLComputePipelineState> flopsPipeline =
            makePipeline(device, compileLibrary(device, kFlopsSource, @"flops"), @"flops_chain");
        const uint32_t flopsThreads = 128 * 1024, flopsIterations = 4096;
        id<MTLBuffer> flopsOut = [device newBufferWithLength:flopsThreads * sizeof(float) * 4
                                                      options:MTLResourceStorageModePrivate];
        id<MTLBuffer> flopsIterBuf = [device newBufferWithBytes:&flopsIterations length:sizeof(uint32_t)
                                                         options:MTLResourceStorageModeShared];
        NSUInteger flopsGroupWidth = MIN((NSUInteger)256, flopsPipeline.maxTotalThreadsPerThreadgroup);
        void (^encodeFlops)(id<MTLCommandBuffer>) = ^(id<MTLCommandBuffer> cb) {
            id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
            [enc setComputePipelineState:flopsPipeline];
            [enc setBuffer:flopsOut offset:0 atIndex:0];
            [enc setBuffer:flopsIterBuf offset:0 atIndex:1];
            [enc dispatchThreads:MTLSizeMake(flopsThreads, 1, 1) threadsPerThreadgroup:MTLSizeMake(flopsGroupWidth, 1, 1)];
            [enc endEncoding];
        };
        const int flopsRepeats = 5;
        double flopsWall[5], flopsGpu[5];
        for (int i = 0; i < 2; ++i) { double w, g; runOnce(queue, encodeFlops, &w, &g); } // warmups
        for (int i = 0; i < flopsRepeats; ++i) runOnce(queue, encodeFlops, &flopsWall[i], &flopsGpu[i]);
        // 8 accumulators * 2 fma-chained ops/iter * 2 flops/fma * 4 lanes/float4 per thread.
        const double totalGFLOPS = (double)flopsIterations * 8.0 * 2.0 * 2.0 * 4.0 * flopsThreads / 1e9;
        double bestWallGFLOPS, medianWallGFLOPS, bestGpuGFLOPS = 0, medianGpuGFLOPS = 0;
        throughputStats(totalGFLOPS, flopsWall, flopsRepeats, &bestWallGFLOPS, &medianWallGFLOPS);
        BOOL haveGpuTimes = flopsGpu[0] > 0;
        if (haveGpuTimes) throughputStats(totalGFLOPS, flopsGpu, flopsRepeats, &bestGpuGFLOPS, &medianGpuGFLOPS);
        printf("FLOPS_WALL_BEST_GFLOPS %.3f\n", bestWallGFLOPS);
        printf("FLOPS_WALL_MEDIAN_GFLOPS %.3f\n", medianWallGFLOPS);
        printf("FLOPS_WALL_BEST_CLOCK_MHZ %.1f\n", clockMHzFromGFLOPS(bestWallGFLOPS));
        printf("FLOPS_WALL_MEDIAN_CLOCK_MHZ %.1f\n", clockMHzFromGFLOPS(medianWallGFLOPS));
        printf("FLOPS_GPU_BEST_GFLOPS %.3f\n", bestGpuGFLOPS);
        printf("FLOPS_GPU_MEDIAN_GFLOPS %.3f\n", medianGpuGFLOPS);
        printf("FLOPS_GPU_BEST_CLOCK_MHZ %.1f\n", clockMHzFromGFLOPS(bestGpuGFLOPS));
        printf("FLOPS_GPU_MEDIAN_CLOCK_MHZ %.1f\n", clockMHzFromGFLOPS(medianGpuGFLOPS));

        // ---- Test 2: bandwidth (blit engine, then a compute float4 copy on the same buffers) ----
        const NSUInteger bandwidthBytes = 256ULL * 1024ULL * 1024ULL;
        const double bandwidthGB = 2.0 * bandwidthBytes / 1e9; // read+write
        id<MTLBuffer> bwSrc = [device newBufferWithLength:bandwidthBytes options:MTLResourceStorageModePrivate];
        id<MTLBuffer> bwDst = [device newBufferWithLength:bandwidthBytes options:MTLResourceStorageModePrivate];
        void (^encodeBlit)(id<MTLCommandBuffer>) = ^(id<MTLCommandBuffer> cb) {
            id<MTLBlitCommandEncoder> blit = [cb blitCommandEncoder];
            [blit copyFromBuffer:bwSrc sourceOffset:0 toBuffer:bwDst destinationOffset:0 size:bandwidthBytes];
            [blit endEncoding];
        };
        const int bwRepeats = 5;
        double blitWall[5], blitGpu[5], bestBlitGBs, medianBlitGBs;
        { double w, g; runOnce(queue, encodeBlit, &w, &g); } // warmup
        for (int i = 0; i < bwRepeats; ++i) runOnce(queue, encodeBlit, &blitWall[i], &blitGpu[i]);
        throughputStats(bandwidthGB, blitWall, bwRepeats, &bestBlitGBs, &medianBlitGBs);
        printf("BLIT_BANDWIDTH_BEST_GBS %.3f\n", bestBlitGBs);
        printf("BLIT_BANDWIDTH_MEDIAN_GBS %.3f\n", medianBlitGBs);
        if (blitGpu[0] > 0) {
            double bestGpuGBs, medianGpuGBs;
            throughputStats(bandwidthGB, blitGpu, bwRepeats, &bestGpuGBs, &medianGpuGBs);
            printf("BLIT_BANDWIDTH_GPU_BEST_GBS %.3f\n", bestGpuGBs);
            printf("BLIT_BANDWIDTH_GPU_MEDIAN_GBS %.3f\n", medianGpuGBs);
        }

        id<MTLComputePipelineState> copyPipeline =
            makePipeline(device, compileLibrary(device, kCopySource, @"copy"), @"copy_f4");
        const uint32_t copyThreads = (uint32_t)(bandwidthBytes / (4 * sizeof(float)));
        NSUInteger copyGroupWidth = MIN((NSUInteger)256, copyPipeline.maxTotalThreadsPerThreadgroup);
        void (^encodeCopyKernel)(id<MTLCommandBuffer>) = ^(id<MTLCommandBuffer> cb) {
            id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
            [enc setComputePipelineState:copyPipeline];
            [enc setBuffer:bwDst offset:0 atIndex:0];
            [enc setBuffer:bwSrc offset:0 atIndex:1];
            [enc dispatchThreads:MTLSizeMake(copyThreads, 1, 1) threadsPerThreadgroup:MTLSizeMake(copyGroupWidth, 1, 1)];
            [enc endEncoding];
        };
        double copyWall[5], copyGpu[5], bestCopyGBs, medianCopyGBs;
        { double w, g; runOnce(queue, encodeCopyKernel, &w, &g); } // warmup
        for (int i = 0; i < bwRepeats; ++i) runOnce(queue, encodeCopyKernel, &copyWall[i], &copyGpu[i]);
        throughputStats(bandwidthGB, copyWall, bwRepeats, &bestCopyGBs, &medianCopyGBs);
        printf("COMPUTE_COPY_BANDWIDTH_BEST_GBS %.3f\n", bestCopyGBs);
        printf("COMPUTE_COPY_BANDWIDTH_MEDIAN_GBS %.3f\n", medianCopyGBs);
        if (copyGpu[0] > 0) {
            double bestGpuGBs, medianGpuGBs;
            throughputStats(bandwidthGB, copyGpu, bwRepeats, &bestGpuGBs, &medianGpuGBs);
            printf("COMPUTE_COPY_BANDWIDTH_GPU_BEST_GBS %.3f\n", bestGpuGBs);
            printf("COMPUTE_COPY_BANDWIDTH_GPU_MEDIAN_GBS %.3f\n", medianGpuGBs);
        }

        // ---- Test 3: RGBA8 -> NV12 conversion, 3840x2160 ----
        const NSUInteger frameW = 3840, frameH = 2160;
        MTLTextureDescriptor *rgbaDesc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
            width:frameW height:frameH mipmapped:NO];
        rgbaDesc.usage = MTLTextureUsageShaderRead; rgbaDesc.storageMode = MTLStorageModePrivate;
        id<MTLTexture> rgbaTexture = [device newTextureWithDescriptor:rgbaDesc];
        MTLTextureDescriptor *yDesc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatR8Unorm
            width:frameW height:frameH mipmapped:NO];
        yDesc.usage = MTLTextureUsageShaderWrite; yDesc.storageMode = MTLStorageModePrivate;
        id<MTLTexture> yTexture = [device newTextureWithDescriptor:yDesc];
        MTLTextureDescriptor *uvDesc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRG8Unorm
            width:frameW / 2 height:frameH / 2 mipmapped:NO];
        uvDesc.usage = MTLTextureUsageShaderWrite; uvDesc.storageMode = MTLStorageModePrivate;
        id<MTLTexture> uvTexture = [device newTextureWithDescriptor:uvDesc];
        if (!rgbaTexture || !yTexture || !uvTexture) fail(@"texture allocation failed");

        // Fill the source texture once via a shared staging buffer + blit upload, so the
        // conversion kernel below reads real (non-uninitialized) private storage.
        NSUInteger stagingBytesPerRow = frameW * 4, stagingBytes = stagingBytesPerRow * frameH;
        id<MTLBuffer> staging = [device newBufferWithLength:stagingBytes options:MTLResourceStorageModeShared];
        uint8_t *stagingBytesPtr = staging.contents;
        for (NSUInteger i = 0; i < stagingBytes; ++i) stagingBytesPtr[i] = (uint8_t)(i * 2654435761u);
        id<MTLCommandBuffer> fillCmd = [queue commandBuffer];
        id<MTLBlitCommandEncoder> fillBlit = [fillCmd blitCommandEncoder];
        [fillBlit copyFromBuffer:staging sourceOffset:0 sourceBytesPerRow:stagingBytesPerRow
             sourceBytesPerImage:stagingBytes sourceSize:MTLSizeMake(frameW, frameH, 1)
                      toTexture:rgbaTexture destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0, 0, 0)];
        [fillBlit endEncoding];
        [fillCmd commit];
        [fillCmd waitUntilCompleted];
        if (fillCmd.error) fail(@"staging upload failed");

        id<MTLComputePipelineState> convertPipeline =
            makePipeline(device, compileLibrary(device, kConvertSource, @"convert"), @"rgba_to_nv12");
        NSUInteger convertGroupSide = 16;
        MTLSize convertGroupSize = MTLSizeMake(convertGroupSide, convertGroupSide, 1);
        MTLSize convertGridSize = MTLSizeMake((frameW / 2 + convertGroupSide - 1) / convertGroupSide,
                                             (frameH / 2 + convertGroupSide - 1) / convertGroupSide, 1);
        void (^encodeConvert)(id<MTLCommandBuffer>) = ^(id<MTLCommandBuffer> cb) {
            id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
            [enc setComputePipelineState:convertPipeline];
            [enc setTexture:rgbaTexture atIndex:0];
            [enc setTexture:yTexture atIndex:1];
            [enc setTexture:uvTexture atIndex:2];
            [enc dispatchThreadgroups:convertGridSize threadsPerThreadgroup:convertGroupSize];
            [enc endEncoding];
        };
        const int convertRepeats = 10;
        double convertWall[10], convertGpu[10];
        { double w, g; runOnce(queue, encodeConvert, &w, &g); } // warmup
        for (int i = 0; i < convertRepeats; ++i) runOnce(queue, encodeConvert, &convertWall[i], &convertGpu[i]);
        printf("CONVERT_WALL_MEAN_MS %.4f\n", meanOf(convertWall, convertRepeats) * 1000.0);
        printf("CONVERT_WALL_MIN_MS %.4f\n", minOf(convertWall, convertRepeats) * 1000.0);
        if (convertGpu[0] > 0) {
            printf("CONVERT_GPU_MEAN_MS %.4f\n", meanOf(convertGpu, convertRepeats) * 1000.0);
            printf("CONVERT_GPU_MIN_MS %.4f\n", minOf(convertGpu, convertRepeats) * 1000.0);
        }

        // ---- Test 4: short-kernel round-trip latency (commit to waitUntilCompleted) ----
        id<MTLComputePipelineState> trivialPipeline =
            makePipeline(device, compileLibrary(device, kTrivialSource, @"trivial"), @"trivial");
        id<MTLBuffer> trivialBuf = [device newBufferWithLength:sizeof(uint32_t) options:MTLResourceStorageModeShared];
        void (^encodeTrivial)(id<MTLCommandBuffer>) = ^(id<MTLCommandBuffer> cb) {
            id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
            [enc setComputePipelineState:trivialPipeline];
            [enc setBuffer:trivialBuf offset:0 atIndex:0];
            [enc dispatchThreads:MTLSizeMake(1, 1, 1) threadsPerThreadgroup:MTLSizeMake(1, 1, 1)];
            [enc endEncoding];
        };
        const int latencyRepeats = 20;
        double latencyWall[20];
        { double w, g; runOnce(queue, encodeTrivial, &w, &g); } // warmup
        for (int i = 0; i < latencyRepeats; ++i) { double g; runOnce(queue, encodeTrivial, &latencyWall[i], &g); }
        printf("LATENCY_MEAN_MS %.4f\n", meanOf(latencyWall, latencyRepeats) * 1000.0);
        printf("LATENCY_MIN_MS %.4f\n", minOf(latencyWall, latencyRepeats) * 1000.0);

        alarm(0);
        printf("{\"status\":\"result\",\"passed\":true,\"device\":\"%s\",\"registry_id\":%llu,"
               "\"flops_wall_best_gflops\":%.3f,\"flops_wall_median_gflops\":%.3f,"
               "\"flops_wall_best_clock_mhz\":%.1f,\"flops_wall_median_clock_mhz\":%.1f,"
               "\"flops_gpu_best_gflops\":%.3f,\"flops_gpu_median_gflops\":%.3f,"
               "\"flops_gpu_best_clock_mhz\":%.1f,\"flops_gpu_median_clock_mhz\":%.1f,"
               "\"blit_bandwidth_best_gbs\":%.3f,\"blit_bandwidth_median_gbs\":%.3f,"
               "\"compute_copy_bandwidth_best_gbs\":%.3f,\"compute_copy_bandwidth_median_gbs\":%.3f,"
               "\"convert_wall_mean_ms\":%.4f,\"convert_wall_min_ms\":%.4f,"
               "\"latency_mean_ms\":%.4f,\"latency_min_ms\":%.4f,\"have_gpu_times\":%s}\n",
               device.name.UTF8String, (unsigned long long)device.registryID,
               bestWallGFLOPS, medianWallGFLOPS, clockMHzFromGFLOPS(bestWallGFLOPS), clockMHzFromGFLOPS(medianWallGFLOPS),
               bestGpuGFLOPS, medianGpuGFLOPS, clockMHzFromGFLOPS(bestGpuGFLOPS), clockMHzFromGFLOPS(medianGpuGFLOPS),
               bestBlitGBs, medianBlitGBs, bestCopyGBs, medianCopyGBs,
               meanOf(convertWall, convertRepeats) * 1000.0, minOf(convertWall, convertRepeats) * 1000.0,
               meanOf(latencyWall, latencyRepeats) * 1000.0, minOf(latencyWall, latencyRepeats) * 1000.0,
               haveGpuTimes ? "true" : "false");
        return 0;
    }
}
