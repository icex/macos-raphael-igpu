// Diagnostic probe: exactly one small Metal compute submission.
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
    printf("RGPU_SMALL_METAL_RESULT %.*s\n", (int)data.length, (const char *)data.bytes);
    fflush(stdout);
}

static void fail(NSString *reason) {
    report[@"error"] = reason;
    report[@"passed"] = @NO;
    emit();
    _exit(1);
}

static void deadline(int signal_number) {
    (void)signal_number;
    const char message[] = "RGPU_SMALL_METAL_TIMEOUT process deadline exceeded\n";
    write(STDOUT_FILENO, message, sizeof(message) - 1);
    _exit(124);
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        signal(SIGALRM, deadline);
        alarm(45);
        report = [@{ @"run_id": argc > 1 ? @(argv[1]) : @"manual",
                    @"passed": @NO, @"completed_command_buffers": @0,
                    @"values_checked": @0 } mutableCopy];
        char *end = NULL;
        unsigned long long expiry = argc == 3 ? strtoull(argv[2], &end, 10) : 0;
        unsigned long long now = (unsigned long long)time(NULL);
        if (!expiry || !end || *end || expiry <= now || expiry - now > 70)
            fail(@"probe delivery expired or guest clock is outside the permitted window");
        alarm((unsigned int)MIN(45ULL, expiry - now));
        id<MTLDevice> device = nil;
        for (id<MTLDevice> candidate in MTLCopyAllDevices())
            if ([candidate.name isEqualToString:@"AMD Radeon Navi23"]) { device = candidate; break; }
        if (!device) fail(@"AMD Radeon Navi23 Metal device is absent");
        report[@"device"] = device.name;
        report[@"registry_id"] = @(device.registryID);
        report[@"metal3"] = @([device supportsFamily:MTLGPUFamilyMetal3]);
        if (![report[@"metal3"] boolValue]) fail(@"device does not advertise Metal 3");
        NSError *error = nil;
        NSString *source = @"#include <metal_stdlib>\nusing namespace metal; kernel void one(device const uint *a [[buffer(0)]], device uint *b [[buffer(1)]], constant uint &salt [[buffer(2)]]) { b[0] = a[0] ^ salt; }";
        id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
        if (!library) fail([NSString stringWithFormat:@"shader compile: %@", error]);
        id<MTLComputePipelineState> pipeline = [device newComputePipelineStateWithFunction:[library newFunctionWithName:@"one"] error:&error];
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!pipeline || !queue) fail(@"compute pipeline or queue creation failed");
        id<MTLBuffer> input = [device newBufferWithLength:sizeof(uint32_t) options:MTLResourceStorageModeShared];
        id<MTLBuffer> output = [device newBufferWithLength:sizeof(uint32_t) options:MTLResourceStorageModeShared];
        if (!input || !output) fail(@"small buffer allocation failed");
        uint32_t value = 0x13579bdf, salt = 0x2468ace0;
        *(uint32_t *)input.contents = value;
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
        if (!command || !encoder) fail(@"command or encoder creation failed");
        [encoder setComputePipelineState:pipeline];
        [encoder setBuffer:input offset:0 atIndex:0];
        [encoder setBuffer:output offset:0 atIndex:1];
        [encoder setBytes:&salt length:sizeof(salt) atIndex:2];
        [encoder dispatchThreads:MTLSizeMake(1, 1, 1) threadsPerThreadgroup:MTLSizeMake(1, 1, 1)];
        [encoder endEncoding];
        dispatch_semaphore_t done = dispatch_semaphore_create(0);
        [command addCompletedHandler:^(id<MTLCommandBuffer> ignored) { (void)ignored; dispatch_semaphore_signal(done); }];
        [command commit];
        if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC)))
            fail(@"GPU completion timeout after 5 seconds");
        if (command.status != MTLCommandBufferStatusCompleted || command.error)
            fail([NSString stringWithFormat:@"command failed: status=%lu error=%@", (unsigned long)command.status, command.error]);
        report[@"completed_command_buffers"] = @1;
        report[@"values_checked"] = @1;
        report[@"value"] = @(*(uint32_t *)output.contents);
        if (*(uint32_t *)output.contents != (value ^ salt)) fail(@"small compute mismatch");
        report[@"passed"] = @YES;
        emit();
        _exit(0);
    }
}
