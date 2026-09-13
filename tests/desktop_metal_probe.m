// Desktop evidence probe: one small compute check on the Metal device, then the
// driver-side evidence that the macOS desktop uses the same device: which Metal
// device drives each active display, and which processes (WindowServer in
// particular) hold IOAccelerator user clients on this device.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOKit/IOKitLib.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static NSMutableDictionary *report;

static void emit(void) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:nil];
    printf("RGPU_DESKTOP_METAL_RESULT %.*s\n", (int)data.length, (const char *)data.bytes);
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
    const char message[] = "RGPU_DESKTOP_METAL_TIMEOUT process deadline exceeded\n";
    write(STDOUT_FILENO, message, sizeof(message) - 1);
    _exit(124);
}

static id plistValue(id value) {
    if ([value isKindOfClass:[NSNumber class]] || [value isKindOfClass:[NSString class]]) return value;
    return [value description];
}

static NSArray *acceleratorEvidence(uint64_t metalRegistryId, BOOL *windowServerClient) {
    NSMutableArray *out = [NSMutableArray array];
    io_iterator_t services = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOAccelerator"),
                                     &services) != KERN_SUCCESS)
        return out;
    io_registry_entry_t service;
    while ((service = IOIteratorNext(services)) != IO_OBJECT_NULL) {
        uint64_t entryId = 0;
        IORegistryEntryGetRegistryEntryID(service, &entryId);
        io_name_t className = {0};
        IOObjectGetClass(service, className);
        NSMutableDictionary *entry = [@{ @"registry_id": @(entryId),
                                         @"class": @(className) } mutableCopy];
        CFTypeRef stats = IORegistryEntryCreateCFProperty(service, CFSTR("PerformanceStatistics"),
                                                          kCFAllocatorDefault, 0);
        if (stats) {
            NSDictionary *dict = CFBridgingRelease(stats);
            NSMutableDictionary *picked = [NSMutableDictionary dictionary];
            for (NSString *key in @[ @"Device Utilization %", @"Renderer Utilization %",
                                     @"Tiler Utilization %", @"In use system memory",
                                     @"Alloc system memory" ]) {
                if (dict[key]) picked[key] = plistValue(dict[key]);
            }
            entry[@"performance"] = picked;
        }
        NSMutableArray *clients = [NSMutableArray array];
        io_iterator_t children = IO_OBJECT_NULL;
        if (IORegistryEntryGetChildIterator(service, kIOServicePlane, &children) == KERN_SUCCESS) {
            io_registry_entry_t child;
            while ((child = IOIteratorNext(children)) != IO_OBJECT_NULL) {
                CFTypeRef creator = IORegistryEntryCreateCFProperty(child, CFSTR("IOUserClientCreator"),
                                                                    kCFAllocatorDefault, 0);
                if (creator) {
                    NSString *text = plistValue(CFBridgingRelease(creator));
                    [clients addObject:text];
                    if ([text containsString:@"WindowServer"]) *windowServerClient = YES;
                }
                IOObjectRelease(child);
            }
            IOObjectRelease(children);
        }
        entry[@"user_clients"] = clients;
        entry[@"same_as_metal_device"] = @(entryId == metalRegistryId);
        [out addObject:entry];
        IOObjectRelease(service);
    }
    IOObjectRelease(services);
    return out;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        signal(SIGALRM, deadline);
        alarm(45);
        report = [@{ @"run_id": argc > 1 ? @(argv[1]) : @"manual", @"passed": @NO,
                     @"completed_command_buffers": @0, @"values_checked": @0 } mutableCopy];
        char *end = NULL;
        unsigned long long expiry = argc == 3 ? strtoull(argv[2], &end, 10) : 0;
        if (argc != 3 || end == NULL || *end != '\0' || (unsigned long long)time(NULL) > expiry)
            fail(@"invalid or expired run permit");

        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) fail(@"no Metal device");
        report[@"device"] = device.name;
        report[@"registry_id"] = @(device.registryID);
        report[@"metal3"] = @([device supportsFamily:MTLGPUFamilyMetal3]);

        NSError *error = nil;
        id<MTLLibrary> library = [device newLibraryWithSource:
            @"#include <metal_stdlib>\nusing namespace metal;\n"
             "kernel void mix(device uint &v [[buffer(0)]], constant uint &s [[buffer(1)]]) { v ^= s; }"
                                                      options:nil error:&error];
        id<MTLFunction> function = [library newFunctionWithName:@"mix"];
        id<MTLComputePipelineState> pipeline = function ?
            [device newComputePipelineStateWithFunction:function error:&error] : nil;
        id<MTLCommandQueue> queue = [device newCommandQueue];
        if (!pipeline || !queue) fail(@"compute pipeline or queue creation failed");
        const uint32_t value = (uint32_t)arc4random(), salt = 0x5a5aa5a5u;
        id<MTLBuffer> output = [device newBufferWithBytes:&value length:sizeof(value)
                                                  options:MTLResourceStorageModeShared];
        id<MTLBuffer> salts = [device newBufferWithBytes:&salt length:sizeof(salt)
                                                 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];
        [encoder setBuffer:output offset:0 atIndex:0];
        [encoder setBuffer:salts offset:0 atIndex:1];
        [encoder dispatchThreads:MTLSizeMake(1, 1, 1) threadsPerThreadgroup:MTLSizeMake(1, 1, 1)];
        [encoder endEncoding];
        [command commit];
        [command waitUntilCompleted];
        if (command.status != MTLCommandBufferStatusCompleted) fail(@"compute command did not complete");
        report[@"completed_command_buffers"] = @1;
        if (*(uint32_t *)output.contents != (value ^ salt)) fail(@"compute mismatch");
        report[@"values_checked"] = @1;

        CGDirectDisplayID displays[16];
        uint32_t displayCount = 0;
        NSMutableArray *displayRows = [NSMutableArray array];
        BOOL displayOnDevice = NO;
        if (CGGetActiveDisplayList(16, displays, &displayCount) == kCGErrorSuccess) {
            for (uint32_t i = 0; i < displayCount; ++i) {
                id<MTLDevice> displayDevice = CGDirectDisplayCopyCurrentMetalDevice(displays[i]);
                BOOL same = displayDevice && displayDevice.registryID == device.registryID;
                displayOnDevice |= same;
                [displayRows addObject:@{ @"id": @(displays[i]),
                                          @"width": @(CGDisplayPixelsWide(displays[i])),
                                          @"height": @(CGDisplayPixelsHigh(displays[i])),
                                          @"main": @(CGDisplayIsMain(displays[i]) != 0),
                                          @"metal_device": displayDevice ? displayDevice.name : @"none",
                                          @"same_device": @(same) }];
            }
        }
        report[@"displays"] = displayRows;
        report[@"display_on_device"] = @(displayOnDevice);
        BOOL windowServerClient = NO;
        report[@"accelerators"] = acceleratorEvidence(device.registryID, &windowServerClient);
        report[@"windowserver_accelerator_client"] = @(windowServerClient);
        report[@"passed"] = @YES;
        emit();
    }
    return 0;
}
