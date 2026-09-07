// GPU execution acceptance probe; compile using tools/metal-test.py --prepare-only.
// Managed buffers follow Apple's "Synchronizing a managed resource in macOS" example.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <dispatch/dispatch.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static NSMutableDictionary *report;

static void emit(void) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:nil];
    printf("RGPU_METAL_RESULT %.*s\n", (int)data.length, (const char *)data.bytes);
    fflush(stdout);
}

static void fail(NSString *reason) {
    report[@"error"] = reason;
    report[@"passed"] = @NO;
    emit();
    // Avoid driver-backed object destruction after a GPU timeout.
    _exit(1);
}

static void deadline(int number) {
    (void)number;
    const char message[] = "RGPU_METAL_TIMEOUT process deadline exceeded\n";
    write(STDOUT_FILENO, message, sizeof(message) - 1);
    _exit(124);
}

static void stage(const char *name) {
    printf("RGPU_METAL_STAGE %s\n", name);
    fflush(stdout);
}

static void complete(id<MTLCommandBuffer> command) {
    if (!command) fail(@"command buffer creation failed");
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    [command addCompletedHandler:^(id<MTLCommandBuffer> ignored) {
        (void)ignored;
        dispatch_semaphore_signal(done);
    }];
    stage("commit");
    [command commit];
    if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)))
        fail(@"GPU completion timeout after 5 seconds");
    if (command.status != MTLCommandBufferStatusCompleted || command.error)
        fail([NSString stringWithFormat:@"command failed: status=%lu error=%@",
              (unsigned long)command.status, command.error]);
    report[@"completed_command_buffers"] = @([report[@"completed_command_buffers"] intValue] + 1);
}

static NSString *shader = @"#include <metal_stdlib>\n"
    "using namespace metal;\n"
    "kernel void calculate(device const uint *a [[buffer(0)]], "
    "device uint *b [[buffer(1)]], constant uint &salt [[buffer(2)]], "
    "uint i [[thread_position_in_grid]]) { "
    "b[i] = (a[i] * 1664525u + salt) ^ (i * 1013904223u); }\n"
    "vertex float4 vertex_main(uint i [[vertex_id]]) { "
    "const float2 p[3] = {float2(-1,-1), float2(3,-1), float2(-1,3)}; "
    "return float4(p[i],0,1); }\n"
    "fragment float4 fragment_main(float4 p [[position]], constant uint &salt [[buffer(0)]]) { "
    "uint2 xy=uint2(p.xy); return float4(float(xy.x)/255.0f, float(xy.y)/255.0f, "
    "float(salt & 255u)/255.0f, 1); }\n";

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        signal(SIGALRM, deadline);
        alarm(45);
        report = [@{@"run_id": argc > 1 ? @(argv[1]) : @"manual", @"passed": @NO,
                    @"compute_rounds": @0, @"compute_values_checked": @0,
                    @"render_pixels_checked": @0, @"completed_command_buffers": @0}
                  mutableCopy];
        char *end = NULL;
        unsigned long long expiry = argc == 3 ? strtoull(argv[2], &end, 10) : 0;
        unsigned long long now = (unsigned long long)time(NULL);
        if (!expiry || !end || *end || expiry <= now || expiry - now > 70)
            fail(@"probe delivery expired or guest clock is outside the permitted window");
        alarm((unsigned int)MIN(45ULL, expiry - now));
        uint32_t runSeed = arc4random();
        report[@"seed"] = @(runSeed);
        stage("enumerate");
        id<MTLDevice> device = nil;
        for (id<MTLDevice> candidate in MTLCopyAllDevices()) {
            if ([candidate.name isEqualToString:@"AMD Radeon Navi23"]) {
                device = candidate;
                break;
            }
        }
        if (!device) fail(@"AMD Radeon Navi23 Metal device is absent");
        report[@"device"] = device.name;
        report[@"registry_id"] = @(device.registryID);
        report[@"metal3"] = @([device supportsFamily:MTLGPUFamilyMetal3]);
        if (![report[@"metal3"] boolValue]) fail(@"device does not advertise Metal 3");
        stage("compile_shaders");
        NSError *error = nil;
        id<MTLLibrary> library = [device newLibraryWithSource:shader options:nil error:&error];
        if (!library) fail([NSString stringWithFormat:@"shader compile: %@", error]);
        id<MTLComputePipelineState> pipeline = [device newComputePipelineStateWithFunction:
            [library newFunctionWithName:@"calculate"] error:&error];
        if (!pipeline) fail([NSString stringWithFormat:@"compute pipeline: %@", error]);
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!queue) fail(@"command queue creation failed");
        const NSUInteger count = 65536, length = count * sizeof(uint32_t);
        id<MTLBuffer> input = [device newBufferWithLength:length options:MTLResourceStorageModeManaged];
        id<MTLBuffer> output = [device newBufferWithLength:length options:MTLResourceStorageModeManaged];
        if (!input || !output) fail(@"compute buffer allocation failed");
        for (uint32_t round = 0; round < 3; round++) {
            stage("compute");
            uint32_t *a = input.contents, *b = output.contents;
            uint32_t salt = runSeed + round * 7919u;
            for (uint32_t i = 0; i < count; i++) {
                a[i] = (i ^ 0xa5a55a5au) + runSeed + round * 977u;
                b[i] = 0xdeadbeefu;
            }
            [input didModifyRange:NSMakeRange(0, length)];
            [output didModifyRange:NSMakeRange(0, length)];
            id<MTLCommandBuffer> command = [queue commandBuffer];
            if (!command) fail(@"compute command creation failed");
            id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
            if (!encoder) fail(@"compute encoder creation failed");
            [encoder setComputePipelineState:pipeline];
            [encoder setBuffer:input offset:0 atIndex:0];
            [encoder setBuffer:output offset:0 atIndex:1];
            [encoder setBytes:&salt length:sizeof(salt) atIndex:2];
            NSUInteger width = MIN((NSUInteger)64, pipeline.maxTotalThreadsPerThreadgroup);
            if (!width) fail(@"compute pipeline has zero threadgroup capacity");
            [encoder dispatchThreads:MTLSizeMake(count, 1, 1)
               threadsPerThreadgroup:MTLSizeMake(width, 1, 1)];
            [encoder endEncoding];
            id<MTLBlitCommandEncoder> sync = [command blitCommandEncoder];
            if (!sync) fail(@"compute synchronization encoder creation failed");
            [sync synchronizeResource:output];
            [sync endEncoding];
            complete(command);
            for (uint32_t i = 0; i < count; i++) {
                uint32_t expected = (a[i] * 1664525u + salt) ^ (i * 1013904223u);
                if (b[i] != expected)
                    fail([NSString stringWithFormat:@"compute mismatch round=%u index=%u got=%#x expected=%#x",
                          round, i, b[i], expected]);
            }
            report[@"compute_rounds"] = @(round + 1);
            report[@"compute_values_checked"] = @((round + 1) * count);
        }
        stage("render");
        MTLRenderPipelineDescriptor *desc = [MTLRenderPipelineDescriptor new];
        desc.vertexFunction = [library newFunctionWithName:@"vertex_main"];
        desc.fragmentFunction = [library newFunctionWithName:@"fragment_main"];
        desc.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        id<MTLRenderPipelineState> render = [device newRenderPipelineStateWithDescriptor:desc error:&error];
        if (!render) fail([NSString stringWithFormat:@"render pipeline: %@", error]);
        MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:
            MTLPixelFormatRGBA8Unorm width:64 height:64 mipmapped:NO];
        td.storageMode = MTLStorageModePrivate;
        td.usage = MTLTextureUsageRenderTarget;
        id<MTLTexture> texture = [device newTextureWithDescriptor:td];
        id<MTLBuffer> pixels = [device newBufferWithLength:64 * 256 options:MTLResourceStorageModeManaged];
        if (!texture || !pixels) fail(@"render resource allocation failed");
        memset(pixels.contents, 0x5a, pixels.length);
        [pixels didModifyRange:NSMakeRange(0, pixels.length)];
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = texture;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0.25, 0.25, 0.25, 0.25);
        id<MTLCommandBuffer> command = [queue commandBuffer];
        if (!command) fail(@"render command creation failed");
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        if (!encoder) fail(@"render encoder creation failed");
        [encoder setRenderPipelineState:render];
        [encoder setFragmentBytes:&runSeed length:sizeof(runSeed) atIndex:0];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [encoder endEncoding];
        id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
        if (!blit) fail(@"render readback encoder creation failed");
        [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0)
                  sourceSize:MTLSizeMake(64,64,1) toBuffer:pixels destinationOffset:0
         destinationBytesPerRow:256 destinationBytesPerImage:64 * 256];
        [blit synchronizeResource:pixels];
        [blit endEncoding];
        complete(command);
        const uint8_t *bytes = pixels.contents;
        for (NSUInteger y = 0; y < 64; y++) {
            for (NSUInteger x = 0; x < 64; x++) {
                const uint8_t *p = bytes + y * 256 + x * 4;
                if (p[0] != x || p[1] != y || p[2] != (runSeed & 255) || p[3] != 255)
                    fail([NSString stringWithFormat:@"render mismatch x=%lu y=%lu rgba=%u,%u,%u,%u",
                          (unsigned long)x, (unsigned long)y, p[0], p[1], p[2], p[3]]);
            }
        }
        report[@"render_pixels_checked"] = @4096;
        report[@"passed"] = @YES;
        emit();
        _exit(0);
    }
}
