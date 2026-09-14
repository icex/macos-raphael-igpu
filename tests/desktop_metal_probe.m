// Desktop evidence probe: one small compute check on the Metal device, then evidence
// that the macOS desktop uses the same device and renders correctly:
// - which Metal device drives each active display, with display identity and the
//   framebuffer registry entries behind it;
// - which processes (WindowServer in particular) hold IOAccelerator user clients;
// - offscreen render throughput with a readback check of the rendered pixels, plus an
//   exact pixel-identity test (each pixel encodes its own coordinates) across target
//   sizes, repeated in child processes with AMD_ENABLE_PRIM_BATCH_BINNING=0 and =1;
// - a borderless CAMetalLayer window run as the console user drawing a known color
//   pattern with a moving bar, checked in its own drawable readback, in its own window
//   capture, and in the root display capture, with its presentation counts;
// - small JPEGs (desktop thumbnail and full-resolution window crops) for the record.
// Only the compute check gates "passed"; everything else is recorded evidence.
#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>
#import <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/dyld.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static NSMutableDictionary *report;

// Window geometry in global display points, top-left origin (CoreGraphics space).
static const CGFloat kWindowX = 120, kWindowY = 120, kWindowW = 400, kWindowH = 300;

// Three separate libraries so a compile problem in one test cannot take down the others.
static NSString *const kComputeSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "kernel void mix(device uint &v [[buffer(0)]], constant uint &s [[buffer(1)]]) { v ^= s; }\n";

static NSString *const kIdentitySource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "struct IV { float4 p [[position]]; };\n"
     "vertex IV identity_triangle(uint id [[vertex_id]]) {\n"
     "  const float2 q[3] = { float2(-1, -1), float2(3, -1), float2(-1, 3) };\n"
     "  IV v; v.p = float4(q[id], 0, 1); return v; }\n"
     "vertex IV identity_quad(uint id [[vertex_id]]) {\n"
     "  const float2 q[6] = { float2(-1, -1), float2(1, -1), float2(-1, 1), float2(-1, 1), float2(1, -1), float2(1, 1) };\n"
     "  IV v; v.p = float4(q[id], 0, 1); return v; }\n"
     "fragment float4 identity_color(IV in [[stage_in]]) {\n"
     "  uint px = uint(in.p.x);\n"
     "  uint py = uint(in.p.y);\n"
     "  uint hi = ((px >> 8) & 15u) | (((py >> 8) & 15u) << 4);\n"
     "  return float4(float(px & 255u) / 255.0f, float(py & 255u) / 255.0f, float(hi) / 255.0f, 1.0f); }\n";

static NSString *const kShaderSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "struct V { float4 p [[position]]; };\n"
     "vertex V fullscreen(uint id [[vertex_id]]) {\n"
     "  const float2 q[3] = { float2(-1, -1), float2(3, -1), float2(-1, 3) };\n"
     "  V v; v.p = float4(q[id], 0, 1); return v; }\n"
     "vertex V points(uint id [[vertex_id]], constant float4 *p [[buffer(0)]]) { V v; v.p = p[id]; return v; }\n"
     "fragment float4 solid(V in [[stage_in]]) { return float4(1, 1, 0, 1); }\n"
     "fragment float4 ramp(V in [[stage_in]], constant float4 &u [[buffer(0)]]) {\n"
     "  return float4(fract(in.p.x / 64.0), fract(in.p.y / 64.0), u.z, 1); }\n"
     "fragment float4 pattern(V in [[stage_in]], constant float4 &u [[buffer(0)]]) {\n"
     "  float2 uv = in.p.xy / u.xy;\n"
     "  if (uv.y > 0.45 && uv.y < 0.55)\n"
     "    return abs(in.p.x - u.z * u.x) < 0.05 * u.x ? float4(0, 0, 0, 1) : float4(0.5, 0.5, 0.5, 1);\n"
     "  if (uv.y <= 0.45) return uv.x < 0.5 ? float4(1, 0, 0, 1) : float4(0, 1, 0, 1);\n"
     "  return uv.x < 0.5 ? float4(0, 0, 1, 1) : float4(1, 1, 1, 1); }\n";

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
    if ([value isKindOfClass:[NSData class]]) return @{ @"data_bytes": @([(NSData *)value length]) };
    return [value description];
}

static NSString *fnvHex(const UInt8 *bytes, size_t length) {
    uint64_t hash = 1469598103934665603ULL;
    for (size_t i = 0; i < length; ++i) hash = (hash ^ bytes[i]) * 1099511628211ULL;
    return [NSString stringWithFormat:@"%016llx", hash];
}

static id<MTLLibrary> compileLibrary(id<MTLDevice> device, NSString *source, NSString *name,
                                    NSMutableDictionary *errors) {
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:source options:nil error:&error];
    if (!library || error) {
        NSString *text = error.localizedDescription ?: @"unknown";
        if (text.length > 1500) text = [text substringToIndex:1500];
        errors[name] = @{ @"library": @(library != nil), @"message": text };
    }
    return library;
}

static id<MTLRenderPipelineState> renderPipelineFormat(id<MTLDevice> device, id<MTLLibrary> library,
                                                      NSString *vertex, NSString *fragment,
                                                      MTLPixelFormat format) {
    MTLRenderPipelineDescriptor *descriptor = [[MTLRenderPipelineDescriptor alloc] init];
    descriptor.vertexFunction = [library newFunctionWithName:vertex];
    descriptor.fragmentFunction = [library newFunctionWithName:fragment];
    descriptor.colorAttachments[0].pixelFormat = format;
    if (!descriptor.vertexFunction || !descriptor.fragmentFunction) return nil;
    return [device newRenderPipelineStateWithDescriptor:descriptor error:nil];
}

static id<MTLRenderPipelineState> renderPipeline(id<MTLDevice> device, id<MTLLibrary> library,
                                                NSString *vertex, NSString *fragment) {
    return renderPipelineFormat(device, library, vertex, fragment, MTLPixelFormatBGRA8Unorm);
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
        NSMutableSet *clients = [NSMutableSet set];
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
        entry[@"user_clients"] = [[clients allObjects] sortedArrayUsingSelector:@selector(compare:)];
        entry[@"same_as_metal_device"] = @(entryId == metalRegistryId);
        [out addObject:entry];
        IOObjectRelease(service);
    }
    IOObjectRelease(services);
    return out;
}

// Framebuffers and the IODisplay entries under them: which connector has a display
// and whether an EDID was read for it.
static NSArray *framebufferEvidence(void) {
    NSMutableArray *out = [NSMutableArray array];
    io_iterator_t services = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOFramebuffer"),
                                     &services) != KERN_SUCCESS)
        return out;
    io_registry_entry_t service;
    while ((service = IOIteratorNext(services)) != IO_OBJECT_NULL) {
        io_name_t className = {0}, name = {0};
        IOObjectGetClass(service, className);
        IORegistryEntryGetName(service, name);
        NSMutableDictionary *entry = [@{ @"class": @(className), @"name": @(name) } mutableCopy];
        CFMutableDictionaryRef props = NULL;
        if (IORegistryEntryCreateCFProperties(service, &props, kCFAllocatorDefault, 0) == KERN_SUCCESS && props) {
            NSDictionary *dict = CFBridgingRelease(props);
            NSMutableDictionary *picked = [NSMutableDictionary dictionary];
            for (NSString *key in dict) {
                NSString *lower = key.lowercaseString;
                if ([lower containsString:@"connect"] || [lower containsString:@"online"] ||
                    [lower containsString:@"edid"] || [lower containsString:@"display"] ||
                    [lower containsString:@"port"] || [lower containsString:@"iofbcurrent"] ||
                    [lower containsString:@"iofbdependent"] || [lower containsString:@"transform"])
                    picked[key] = plistValue(dict[key]);
            }
            entry[@"properties"] = picked;
        }
        NSMutableArray *displays = [NSMutableArray array];
        io_iterator_t tree = IO_OBJECT_NULL;
        if (IORegistryEntryCreateIterator(service, kIOServicePlane, kIORegistryIterateRecursively,
                                          &tree) == KERN_SUCCESS) {
            io_registry_entry_t child;
            while ((child = IOIteratorNext(tree)) != IO_OBJECT_NULL) {
                if (IOObjectConformsTo(child, "IODisplay")) {
                    io_name_t childClass = {0};
                    IOObjectGetClass(child, childClass);
                    NSMutableDictionary *row = [@{ @"class": @(childClass) } mutableCopy];
                    for (NSString *key in @[ @"DisplayVendorID", @"DisplayProductID",
                                             @"DisplaySerialNumber", @"IODisplayEDID",
                                             @"IODisplayEDIDOriginal", @"IODisplayConnectFlags" ]) {
                        CFTypeRef value = IORegistryEntryCreateCFProperty(child, (__bridge CFStringRef)key,
                                                                          kCFAllocatorDefault, 0);
                        if (value) row[key] = plistValue(CFBridgingRelease(value));
                    }
                    [displays addObject:row];
                }
                IOObjectRelease(child);
            }
            IOObjectRelease(tree);
        }
        entry[@"displays"] = displays;
        [out addObject:entry];
        IOObjectRelease(service);
    }
    IOObjectRelease(services);
    return out;
}

static CGImageRef createDisplayImage(CGDirectDisplayID display) {
    // Unavailable in the macOS 15 SDK headers but still exported at runtime.
    CGImageRef (*create)(CGDirectDisplayID) =
        (CGImageRef (*)(CGDirectDisplayID))dlsym(RTLD_DEFAULT, "CGDisplayCreateImage");
    return create ? create(display) : NULL;
}

// A region of the image drawn into an 8-bit RGBX bitmap in the image's own color
// space, so pixel values are not color-converted and a cropped image's shared data
// provider cannot leak bytes from outside the region.
static NSData *regionPixels(CGImageRef image, CGRect region, size_t *widthOut, size_t *heightOut) {
    CGImageRef part = image ? CGImageCreateWithImageInRect(image, region) : NULL;
    if (!part) return nil;
    size_t width = CGImageGetWidth(part), height = CGImageGetHeight(part);
    NSMutableData *pixels = [NSMutableData dataWithLength:width * height * 4];
    CGColorSpaceRef space = CGImageGetColorSpace(image);
    CGContextRef context = NULL;
    if (space && CGColorSpaceGetModel(space) == kCGColorSpaceModelRGB)
        context = CGBitmapContextCreate(pixels.mutableBytes, width, height, 8, width * 4, space,
                                        kCGImageAlphaNoneSkipLast);
    if (!context) {
        CGColorSpaceRef device = CGColorSpaceCreateDeviceRGB();
        context = CGBitmapContextCreate(pixels.mutableBytes, width, height, 8, width * 4, device,
                                        kCGImageAlphaNoneSkipLast);
        CGColorSpaceRelease(device);
    }
    if (context) {
        CGContextSetBlendMode(context, kCGBlendModeCopy);
        CGContextDrawImage(context, CGRectMake(0, 0, width, height), part);
        CGContextRelease(context);
    }
    CGImageRelease(part);
    if (!context) return nil;
    *widthOut = width;
    *heightOut = height;
    return pixels;
}

static NSDictionary *imageSummary(CGImageRef image) {
    if (!image) return @{ @"captured": @NO };
    CFDataRef data = CGDataProviderCopyData(CGImageGetDataProvider(image));
    NSString *hash = @"";
    uint64_t nonzero = 0;
    if (data) {
        const UInt8 *bytes = CFDataGetBytePtr(data);
        CFIndex length = CFDataGetLength(data);
        hash = fnvHex(bytes, (size_t)length);
        for (CFIndex i = 0; i < length; ++i) nonzero += bytes[i] != 0;
        CFRelease(data);
    }
    return @{ @"captured": @YES, @"width": @(CGImageGetWidth(image)),
              @"height": @(CGImageGetHeight(image)), @"fnv": hash, @"nonzero_bytes": @(nonzero),
              @"bits_per_pixel": @(CGImageGetBitsPerPixel(image)),
              @"bits_per_component": @(CGImageGetBitsPerComponent(image)),
              @"bitmap_info": @(CGImageGetBitmapInfo(image)) };
}

// JPEG of an image region, scaled to at most maxWidth pixels, base64-encoded.
static NSDictionary *jpegOf(CGImageRef image, CGRect region, size_t maxWidth, double quality, NSString *label) {
    if (!image) return @{ @"label": label, @"jpeg_base64": @"" };
    CGImageRef part = CGRectIsNull(region) ? CGImageRetain(image) : CGImageCreateWithImageInRect(image, region);
    if (!part) return @{ @"label": label, @"jpeg_base64": @"" };
    size_t width = CGImageGetWidth(part), height = CGImageGetHeight(part);
    size_t targetWidth = width > maxWidth ? maxWidth : width;
    size_t targetHeight = height * targetWidth / (width ? width : 1);
    CGColorSpaceRef space = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = CGBitmapContextCreate(NULL, targetWidth, targetHeight, 8, 0, space,
                                                 kCGImageAlphaNoneSkipLast);
    CGColorSpaceRelease(space);
    NSMutableData *jpeg = [NSMutableData data];
    if (context) {
        CGContextSetInterpolationQuality(context, kCGInterpolationHigh);
        CGContextDrawImage(context, CGRectMake(0, 0, targetWidth, targetHeight), part);
        CGImageRef scaled = CGBitmapContextCreateImage(context);
        CGImageDestinationRef destination = CGImageDestinationCreateWithData(
            (__bridge CFMutableDataRef)jpeg, CFSTR("public.jpeg"), 1, NULL);
        if (destination && scaled) {
            NSDictionary *options = @{ (__bridge NSString *)kCGImageDestinationLossyCompressionQuality: @(quality) };
            CGImageDestinationAddImage(destination, scaled, (__bridge CFDictionaryRef)options);
            CGImageDestinationFinalize(destination);
        }
        if (destination) CFRelease(destination);
        if (scaled) CGImageRelease(scaled);
        CGContextRelease(context);
    }
    CGImageRelease(part);
    return @{ @"label": label, @"width": @(targetWidth), @"height": @(targetHeight),
              @"jpeg_bytes": @(jpeg.length),
              @"jpeg_base64": jpeg.length && jpeg.length < 120000 ? [jpeg base64EncodedStringWithOptions:0] : @"" };
}

static BOOL colorMatches(NSArray *rgb, int wantR, int wantG, int wantB) {
    if (rgb.count != 3) return NO;
    int want[3] = { wantR, wantG, wantB };
    for (int i = 0; i < 3; ++i) {
        int v = [rgb[i] intValue];
        if (want[i] ? v < 170 : v > 90) return NO;
    }
    return YES;
}

// Offscreen render: a full-target procedural ramp plus 20,000 small triangles in the
// top band, frame after frame for up to 3 seconds, then a readback of the last frame
// checked against the ramp's exact 8-bit values below the band.
static NSDictionary *offscreenThroughput(id<MTLDevice> device, id<MTLLibrary> library,
                                         id<MTLCommandQueue> queue) {
    const NSUInteger width = 1280, height = 1024, triangles = 20000;
    id<MTLRenderPipelineState> ramp = renderPipeline(device, library, @"fullscreen", @"ramp");
    id<MTLRenderPipelineState> solid = renderPipeline(device, library, @"points", @"solid");
    if (!ramp || !solid) return @{ @"error": @"pipeline" };
    MTLTextureDescriptor *descriptor =
        [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                                                           width:width height:height mipmapped:NO];
    descriptor.usage = MTLTextureUsageRenderTarget;
    descriptor.storageMode = MTLStorageModePrivate;
    id<MTLTexture> target = [device newTextureWithDescriptor:descriptor];
    id<MTLBuffer> vertices = [device newBufferWithLength:sizeof(float) * 4 * 3 * triangles
                                                 options:MTLResourceStorageModeShared];
    if (!target || !vertices) return @{ @"error": @"allocation" };
    float *v = vertices.contents;
    srand48(0x52475055);
    for (NSUInteger t = 0; t < triangles; ++t) {
        float cx = (float)(drand48() * 2 - 1), cy = (float)(0.82 + drand48() * 0.16);
        const float dx[3] = { 0, 0.004f, -0.004f }, dy[3] = { 0.008f, -0.004f, -0.004f };
        for (int k = 0; k < 3; ++k) {
            float *q = v + (t * 3 + k) * 4;
            q[0] = cx + dx[k]; q[1] = cy + dy[k]; q[2] = 0; q[3] = 1;
        }
    }
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = target;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    double start = CACurrentMediaTime(), gpuSeconds = 0;
    NSUInteger frames = 0, failures = 0;
    float uniforms[4] = { (float)width, (float)height, 0, 0 };
    while (frames < 1000 && CACurrentMediaTime() - start < 3.0) {
        @autoreleasepool {
            uniforms[2] = (float)(frames % 256) / 255.0f;
            id<MTLCommandBuffer> command = [queue commandBuffer];
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
            [encoder setRenderPipelineState:ramp];
            [encoder setFragmentBytes:uniforms length:sizeof(uniforms) atIndex:0];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [encoder setRenderPipelineState:solid];
            [encoder setVertexBuffer:vertices offset:0 atIndex:0];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:triangles * 3];
            [encoder endEncoding];
            [command commit];
            [command waitUntilCompleted];
            if (command.status != MTLCommandBufferStatusCompleted) { ++failures; break; }
            gpuSeconds += command.GPUEndTime - command.GPUStartTime;
            ++frames;
        }
    }
    double elapsed = CACurrentMediaTime() - start;
    NSMutableDictionary *result = [@{ @"frames": @(frames), @"seconds": @(elapsed),
                                      @"fps": @(elapsed > 0 ? frames / elapsed : 0),
                                      @"gpu_ms_per_frame": @(frames ? gpuSeconds * 1000.0 / frames : 0),
                                      @"triangles_per_frame": @(triangles + 1),
                                      @"failed_command_buffers": @(failures),
                                      @"width": @(width), @"height": @(height) } mutableCopy];
    if (!frames) return result;
    id<MTLBuffer> readback = [device newBufferWithLength:width * height * 4 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> command = [queue commandBuffer];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
               sourceSize:MTLSizeMake(width, height, 1) toBuffer:readback destinationOffset:0
   destinationBytesPerRow:width * 4 destinationBytesPerImage:width * height * 4];
    [blit endEncoding];
    [command commit];
    [command waitUntilCompleted];
    if (command.status != MTLCommandBufferStatusCompleted) { result[@"readback"] = @"failed"; return result; }
    const UInt8 *pixels = readback.contents;
    const int expectBlue = (int)((frames - 1) % 256);
    NSUInteger checked = 0, mismatches = 0, bandYellow = 0;
    NSMutableArray *firstMismatches = [NSMutableArray array];
    for (NSUInteger y = 200; y < height; y += 37) {
        for (NSUInteger x = 3; x < width; x += 41) {
            const UInt8 *p = pixels + (y * width + x) * 4;
            double fx = fmod((x + 0.5) / 64.0, 1.0), fy = fmod((y + 0.5) / 64.0, 1.0);
            int er = (int)lround(fx * 255.0), eg = (int)lround(fy * 255.0);
            ++checked;
            if (abs(p[2] - er) > 1 || abs(p[1] - eg) > 1 || abs(p[0] - expectBlue) > 1) {
                if (firstMismatches.count < 4)
                    [firstMismatches addObject:@[ @(x), @(y), @(p[2]), @(p[1]), @(p[0]), @(er), @(eg), @(expectBlue) ]];
                ++mismatches;
            }
        }
    }
    for (NSUInteger y = 12; y < 90; y += 3)
        for (NSUInteger x = 0; x < width; x += 7) {
            const UInt8 *p = pixels + (y * width + x) * 4;
            bandYellow += p[2] > 250 && p[1] > 250 && p[0] < 5;
        }
    result[@"pixels_checked"] = @(checked);
    result[@"pixel_mismatches"] = @(mismatches);
    result[@"first_mismatches"] = firstMismatches;
    result[@"band_yellow_samples"] = @(bandYellow);
    result[@"frame_fnv"] = fnvHex(pixels, width * height * 4);
    return result;
}

static NSDictionary *checkPatternRegion(CGImageRef image, CGRect region, NSString *label, NSMutableArray *jpegs);

// Decode an identity image (bytes in RGBA or BGRA order) into mismatch statistics.
static void identityStats(const UInt8 *bytes, NSUInteger width, NSUInteger height, BOOL rgba, BOOL wantMap,
                          NSMutableDictionary *result) {
    // Small open-addressing histogram of (dx, dy).
    enum { kSlots = 4096 };
    int32_t keyDx[kSlots], keyDy[kSlots];
    uint32_t counts[kSlots];
    memset(counts, 0, sizeof(counts));
    NSUInteger mismatches = 0, unwritten = 0, overflow = 0;
    NSUInteger blocksW = (width + 15) / 16, blocksH = (height + 15) / 16;
    NSMutableData *map = wantMap ? [NSMutableData dataWithLength:blocksW * blocksH * 4] : nil;
    for (NSUInteger y = 0; y < height; ++y) {
        for (NSUInteger x = 0; x < width; ++x) {
            const UInt8 *p = bytes + (y * width + x) * 4;
            int r = rgba ? p[0] : p[2], g = p[1], b = rgba ? p[2] : p[0], a = p[3];
            int dx = 0, dy = 0;
            if (a != 255) {
                ++unwritten;
                dx = 0x7fff; dy = 0x7fff;
            } else {
                int sx = r | ((b & 15) << 8), sy = g | ((b >> 4) << 8);
                dx = sx - (int)x; dy = sy - (int)y;
            }
            if (dx || dy) {
                ++mismatches;
                uint32_t h = (((uint32_t)dx * 73856093u) ^ ((uint32_t)dy * 19349663u)) & (kSlots - 1);
                unsigned probes = 0;
                while (counts[h] && (keyDx[h] != dx || keyDy[h] != dy) && probes < kSlots) {
                    h = (h + 1) & (kSlots - 1); ++probes;
                }
                if (probes >= kSlots) ++overflow;
                else { keyDx[h] = dx; keyDy[h] = dy; ++counts[h]; }
            }
            if (map && x % 16 == 0 && y % 16 == 0) {
                int16_t *m = (int16_t *)map.mutableBytes + ((y / 16) * blocksW + x / 16) * 2;
                m[0] = (int16_t)dx; m[1] = (int16_t)dy;
            }
        }
    }
    // Top displacements.
    NSMutableArray *top = [NSMutableArray array];
    for (int pick = 0; pick < 8; ++pick) {
        int best = -1;
        for (int i = 0; i < kSlots; ++i)
            if (counts[i] && (best < 0 || counts[i] > counts[best])) best = i;
        if (best < 0) break;
        [top addObject:@[ @(keyDx[best]), @(keyDy[best]), @(counts[best]) ]];
        counts[best] = 0;
    }
    // Tiles (8x8) whose pixels all share one displacement.
    NSUInteger tiles = 0, uniformTiles = 0, displacedUniformTiles = 0;
    for (NSUInteger ty = 0; ty + 8 <= height; ty += 8) {
        for (NSUInteger tx = 0; tx + 8 <= width; tx += 8) {
            ++tiles;
            int firstDx = 0, firstDy = 0;
            BOOL uniform = YES;
            for (NSUInteger y = ty; y < ty + 8 && uniform; ++y) {
                for (NSUInteger x = tx; x < tx + 8; ++x) {
                    const UInt8 *p = bytes + (y * width + x) * 4;
                    int r = rgba ? p[0] : p[2], g = p[1], b = rgba ? p[2] : p[0];
                    int dx = (r | ((b & 15) << 8)) - (int)x, dy = (g | ((b >> 4) << 8)) - (int)y;
                    if (y == ty && x == tx) { firstDx = dx; firstDy = dy; }
                    else if (dx != firstDx || dy != firstDy) { uniform = NO; break; }
                }
            }
            if (uniform) { ++uniformTiles; if (firstDx || firstDy) ++displacedUniformTiles; }
        }
    }
    result[@"pixels"] = @(width * height);
    result[@"mismatches"] = @(mismatches);
    result[@"unwritten"] = @(unwritten);
    result[@"histogram_overflow"] = @(overflow);
    result[@"top_displacements"] = top;
    result[@"tiles8"] = @(tiles);
    result[@"uniform_tiles8"] = @(uniformTiles);
    result[@"displaced_uniform_tiles8"] = @(displacedUniformTiles);
    if (map) {
        result[@"block16_map_w"] = @(blocksW);
        result[@"block16_map_h"] = @(blocksH);
        result[@"block16_map_base64"] = [map base64EncodedStringWithOptions:0];
    }
}

// Exact pixel identity: every pixel encodes its own coordinates, so a readback shows
// for each pixel which position's value landed there. Records mismatches, unwritten
// pixels, the most common displacements, how many 8x8 tiles move as a unit, and
// optionally a per-16x16-block displacement map (int16 dx, dy of each block's first
// pixel, little-endian, base64).
static NSDictionary *identityTest(id<MTLDevice> device, id<MTLLibrary> library, id<MTLCommandQueue> queue,
                                  NSUInteger width, NSUInteger height, BOOL rgba, BOOL quad, BOOL wantMap) {
    MTLPixelFormat format = rgba ? MTLPixelFormatRGBA8Unorm : MTLPixelFormatBGRA8Unorm;
    NSMutableDictionary *result = [@{ @"width": @(width), @"height": @(height),
                                      @"format": rgba ? @"RGBA8" : @"BGRA8",
                                      @"geometry": quad ? @"quad" : @"fullscreen-triangle" } mutableCopy];
    id<MTLRenderPipelineState> pipeline =
        renderPipelineFormat(device, library, quad ? @"identity_quad" : @"identity_triangle", @"identity_color", format);
    MTLTextureDescriptor *descriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format
                                                                                          width:width height:height mipmapped:NO];
    descriptor.usage = MTLTextureUsageRenderTarget;
    descriptor.storageMode = MTLStorageModePrivate;
    id<MTLTexture> target = [device newTextureWithDescriptor:descriptor];
    id<MTLBuffer> readback = [device newBufferWithLength:width * height * 4 options:MTLResourceStorageModeShared];
    if (!pipeline || !target || !readback) {
        result[@"error"] = !library ? @"no identity library" : !pipeline ? @"identity pipeline" : @"allocation";
        return result;
    }
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = target;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 0);
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> command = [queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:pipeline];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:quad ? 6 : 3];
    [encoder endEncoding];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
               sourceSize:MTLSizeMake(width, height, 1) toBuffer:readback destinationOffset:0
   destinationBytesPerRow:width * 4 destinationBytesPerImage:width * height * 4];
    [blit endEncoding];
    [command commit];
    [command waitUntilCompleted];
    if (command.status != MTLCommandBufferStatusCompleted) { result[@"error"] = @"command"; return result; }
    identityStats(readback.contents, width, height, rgba, wantMap, result);
    return result;
}

// Render the identity image once into a Private texture, then read it back several
// ways; plus a render straight into a Managed texture. Separates rendering faults from
// GPU-to-CPU copy faults.
static NSArray *readbackMatrix(id<MTLDevice> device, id<MTLLibrary> library, id<MTLCommandQueue> queue,
                               NSUInteger width, NSUInteger height, MTLClearColor clear) {
    NSMutableArray *rows = [NSMutableArray array];
    MTLPixelFormat format = MTLPixelFormatRGBA8Unorm;
    id<MTLRenderPipelineState> pipeline = library ?
        renderPipelineFormat(device, library, @"identity_triangle", @"identity_color", format) : nil;
    if (!pipeline) return @[ @{ @"error": @"identity pipeline" } ];
    MTLTextureDescriptor *privateDescriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format
                                                                                                 width:width height:height mipmapped:NO];
    privateDescriptor.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;
    privateDescriptor.storageMode = MTLStorageModePrivate;
    MTLTextureDescriptor *managedDescriptor = [privateDescriptor copy];
    managedDescriptor.storageMode = MTLStorageModeManaged;
    id<MTLTexture> privateTexture = [device newTextureWithDescriptor:privateDescriptor];
    id<MTLTexture> managedTarget = [device newTextureWithDescriptor:managedDescriptor];
    id<MTLTexture> managedCopy = [device newTextureWithDescriptor:managedDescriptor];
    id<MTLBuffer> shared = [device newBufferWithLength:width * height * 4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> managed = [device newBufferWithLength:width * height * 4 options:MTLResourceStorageModeManaged];
    if (!privateTexture || !managedTarget || !managedCopy || !shared || !managed)
        return @[ @{ @"error": @"allocation" } ];
    memset(shared.contents, 0x5a, shared.length);
    memset(managed.contents, 0x5a, managed.length);
    [managed didModifyRange:NSMakeRange(0, managed.length)];
    void (^draw)(id<MTLCommandBuffer>, id<MTLTexture>) = ^(id<MTLCommandBuffer> command, id<MTLTexture> target) {
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = target;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].clearColor = clear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        [encoder setRenderPipelineState:pipeline];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        [encoder endEncoding];
    };
    MTLOrigin zero = MTLOriginMake(0, 0, 0);
    MTLSize size = MTLSizeMake(width, height, 1);
    // Render into the Private texture, then copy into a Shared buffer, a Managed buffer and a
    // Managed texture, each in its own command buffer.
    id<MTLCommandBuffer> render = [queue commandBuffer];
    draw(render, privateTexture);
    [render commit];
    [render waitUntilCompleted];
    NSString *renderStatus = render.status == MTLCommandBufferStatusCompleted ? @"ok" : @"failed";
    id<MTLCommandBuffer> copyShared = [queue commandBuffer];
    id<MTLBlitCommandEncoder> blit = [copyShared blitCommandEncoder];
    [blit copyFromTexture:privateTexture sourceSlice:0 sourceLevel:0 sourceOrigin:zero sourceSize:size
                 toBuffer:shared destinationOffset:0 destinationBytesPerRow:width * 4
  destinationBytesPerImage:width * height * 4];
    [blit endEncoding];
    [copyShared commit];
    [copyShared waitUntilCompleted];
    id<MTLCommandBuffer> copyManaged = [queue commandBuffer];
    blit = [copyManaged blitCommandEncoder];
    [blit copyFromTexture:privateTexture sourceSlice:0 sourceLevel:0 sourceOrigin:zero sourceSize:size
                 toBuffer:managed destinationOffset:0 destinationBytesPerRow:width * 4
  destinationBytesPerImage:width * height * 4];
    [blit synchronizeResource:managed];
    [blit endEncoding];
    [copyManaged commit];
    [copyManaged waitUntilCompleted];
    id<MTLCommandBuffer> copyTexture = [queue commandBuffer];
    blit = [copyTexture blitCommandEncoder];
    [blit copyFromTexture:privateTexture sourceSlice:0 sourceLevel:0 sourceOrigin:zero sourceSize:size
                toTexture:managedCopy destinationSlice:0 destinationLevel:0 destinationOrigin:zero];
    [blit synchronizeResource:managedCopy];
    [blit endEncoding];
    [copyTexture commit];
    [copyTexture waitUntilCompleted];
    // Render straight into a Managed texture and synchronize it.
    id<MTLCommandBuffer> direct = [queue commandBuffer];
    draw(direct, managedTarget);
    blit = [direct blitCommandEncoder];
    [blit synchronizeResource:managedTarget];
    [blit endEncoding];
    [direct commit];
    [direct waitUntilCompleted];

    NSMutableData *textureBytes = [NSMutableData dataWithLength:width * height * 4];
    NSMutableData *directBytes = [NSMutableData dataWithLength:width * height * 4];
    [managedCopy getBytes:textureBytes.mutableBytes bytesPerRow:width * 4
               fromRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0];
    [managedTarget getBytes:directBytes.mutableBytes bytesPerRow:width * 4
                 fromRegion:MTLRegionMake2D(0, 0, width, height) mipmapLevel:0];
    struct { NSString *path; const UInt8 *bytes; id<MTLCommandBuffer> command; } paths[] = {
        { @"private->shared-buffer", shared.contents, copyShared },
        { @"private->managed-buffer+sync", managed.contents, copyManaged },
        { @"private->managed-texture+sync", textureBytes.bytes, copyTexture },
        { @"render-into-managed-texture+sync", directBytes.bytes, direct },
    };
    for (size_t i = 0; i < 4; ++i) {
        NSMutableDictionary *row = [@{ @"width": @(width), @"height": @(height), @"format": @"RGBA8",
                                       @"geometry": @"fullscreen-triangle", @"path": paths[i].path,
                                       @"render": renderStatus,
                                       @"command": paths[i].command.status == MTLCommandBufferStatusCompleted ?
                                           @"ok" : @"failed" } mutableCopy];
        identityStats(paths[i].bytes, width, height, YES, NO, row);
        [rows addObject:row];
    }
    return rows;
}

static NSArray *identityMatrix(id<MTLDevice> device, id<MTLLibrary> library, id<MTLCommandQueue> queue,
                               BOOL wantMap) {
    NSMutableArray *rows = [NSMutableArray array];
    const NSUInteger sizes[][2] = { { 64, 64 }, { 256, 256 }, { 512, 512 }, { 1024, 1024 }, { 1280, 1024 } };
    for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        @autoreleasepool {
            [rows addObject:identityTest(device, library, queue, sizes[i][0], sizes[i][1], NO, NO,
                                         wantMap && sizes[i][0] == 1280)];
        }
    }
    @autoreleasepool {
        [rows addObject:identityTest(device, library, queue, 1280, 1024, YES, NO, NO)];
        [rows addObject:identityTest(device, library, queue, 1280, 1024, NO, YES, NO)];
    }
    return rows;
}

// Child mode for render tests under a different driver environment.
static int renderChild(NSString *outputPath, unsigned long long expiry) {
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    const char *env = getenv("AMD_ENABLE_PRIM_BATCH_BINNING");
    result[@"AMD_ENABLE_PRIM_BATCH_BINNING"] = env ? @(env) : [NSNull null];
    signal(SIGALRM, deadline);
    alarm(8);
    if ((unsigned long long)time(NULL) <= expiry) {
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        NSMutableDictionary *errors = [NSMutableDictionary dictionary];
        id<MTLLibrary> library = device ? compileLibrary(device, kShaderSource, @"render", errors) : nil;
        id<MTLLibrary> identity = device ? compileLibrary(device, kIdentitySource, @"identity", errors) : nil;
        id<MTLCommandQueue> queue = [device newCommandQueue];
        result[@"shader_errors"] = errors;
        if (queue) {
            if (library) result[@"offscreen"] = offscreenThroughput(device, library, queue);
            result[@"identity"] = identityMatrix(device, identity, queue, NO);
        } else {
            result[@"error"] = @"device or queue";
        }
    } else {
        result[@"error"] = @"expired";
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
    [data writeToFile:outputPath atomically:NO];
    return 0;
}

// Settings experiments: AMDRadeonX6000MTLDriver computes its AMD_DeviceSettings defaults
// with two immediate constants (24G830 shared cache, offsets from the image header):
//   0x13a7e1  movabs $0x1ff700000,%rax    bits 20-22 and 24-32 (27 enableTexturePipeBankXor,
//                                         29 enableBlitDMA)
//   0x13a82b  movabs $0x1ee000000000,%rax bits 37-39 and 41-44 (36 linearSwizzleTextures is 0)
// A child patches one immediate byte in its own copy of the driver before creating the
// device, then reruns the readback matrix.
static NSDictionary *patchDriverSettings(NSString *variant) {
    static const char *const kDriver =
        "/System/Library/Extensions/AMDRadeonX6000MTLDriver.bundle/Contents/MacOS/AMDRadeonX6000MTLDriver";
    static const uint8_t kLowSettings[] = {0x48, 0xb8, 0x00, 0x00, 0x70, 0xff, 0x01, 0x00, 0x00, 0x00};
    static const uint8_t kHighSettings[] = {0x48, 0xb8, 0x00, 0x00, 0x00, 0x00, 0xe0, 0x1e, 0x00, 0x00};
    if (!dlopen(kDriver, RTLD_NOW | RTLD_GLOBAL)) return @{ @"error": @"dlopen" };
    const struct mach_header *header = NULL;
    for (uint32_t i = 0; i < _dyld_image_count(); ++i)
        if (strcmp(_dyld_get_image_name(i), kDriver) == 0) header = _dyld_get_image_header(i);
    if (!header) return @{ @"error": @"image not found" };
    size_t offset = 0, byteIndex = 0;
    const uint8_t *expected = NULL;
    uint8_t (^change)(uint8_t) = nil;
    if ([variant isEqualToString:@"pipebankxor0"]) {
        offset = 0x13a7e1; expected = kLowSettings; byteIndex = 5;
        change = ^uint8_t(uint8_t v) { return (uint8_t)(v & ~0x08); };
    } else if ([variant isEqualToString:@"blitdma0"]) {
        offset = 0x13a7e1; expected = kLowSettings; byteIndex = 5;
        change = ^uint8_t(uint8_t v) { return (uint8_t)(v & ~0x20); };
    } else if ([variant isEqualToString:@"linearswizzle1"]) {
        offset = 0x13a82b; expected = kHighSettings; byteIndex = 6;
        change = ^uint8_t(uint8_t v) { return (uint8_t)(v | 0x10); };
    } else {
        return @{ @"variant": variant, @"patched": @NO };
    }
    uint8_t *site = (uint8_t *)header + offset;
    if (memcmp(site, expected, 10) != 0) return @{ @"error": @"site bytes differ" };
    const uint8_t before = site[byteIndex], after = change(before);
    const mach_vm_size_t page = (mach_vm_size_t)getpagesize();
    const mach_vm_address_t base = (mach_vm_address_t)(site + byteIndex) & ~(page - 1);
    kern_return_t unlock = mach_vm_protect(mach_task_self(), base, page, FALSE,
                                           VM_PROT_READ | VM_PROT_WRITE | VM_PROT_COPY);
    if (unlock != KERN_SUCCESS) return @{ @"error": @"protect", @"kr": @(unlock) };
    site[byteIndex] = after;
    kern_return_t relock = mach_vm_protect(mach_task_self(), base, page, FALSE,
                                           VM_PROT_READ | VM_PROT_EXECUTE);
    return @{ @"variant": variant, @"patched": @(site[byteIndex] == after), @"before": @(before),
              @"after": @(after), @"relock_kr": @(relock) };
}

static int patchChild(NSString *variant, NSString *outputPath, unsigned long long expiry) {
    NSMutableDictionary *result = [@{ @"variant": variant } mutableCopy];
    signal(SIGALRM, deadline);
    alarm(7);
    if ((unsigned long long)time(NULL) <= expiry) {
        result[@"patch"] = patchDriverSettings(variant);
        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        NSMutableDictionary *errors = [NSMutableDictionary dictionary];
        id<MTLLibrary> identity = device ? compileLibrary(device, kIdentitySource, @"identity", errors) : nil;
        id<MTLCommandQueue> queue = [device newCommandQueue];
        result[@"shader_errors"] = errors;
        if (queue && identity) {
            NSMutableArray *rows = [NSMutableArray array];
            [rows addObjectsFromArray:readbackMatrix(device, identity, queue, 64, 64,
                                                     MTLClearColorMake(0.25, 0.25, 0.25, 0.25))];
            [rows addObjectsFromArray:readbackMatrix(device, identity, queue, 1280, 1024,
                                                     MTLClearColorMake(0, 0, 0, 0))];
            result[@"readback_matrix"] = rows;
        } else {
            result[@"error"] = @"device, library or queue";
        }
    } else {
        result[@"error"] = @"expired";
    }
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
    [data writeToFile:outputPath atomically:NO];
    return 0;
}

static NSDictionary *patchChildRun(const char *selfPath, unsigned long long expiry, NSString *variant) {
    NSString *output = [NSString stringWithFormat:@"/var/tmp/rgpu-patch-%d-%@.json", getpid(), variant];
    [[NSFileManager defaultManager] removeItemAtPath:output error:nil];
    NSTask *task = [[NSTask alloc] init];
    task.launchPath = @(selfPath);
    task.arguments = @[ @"--patch-child", variant, output, [NSString stringWithFormat:@"%llu", expiry] ];
    task.standardOutput = [NSFileHandle fileHandleWithNullDevice];
    task.standardError = [NSFileHandle fileHandleWithNullDevice];
    @try { [task launch]; }
    @catch (NSException *exception) { return @{ @"variant": variant, @"error": @"launch-failed" }; }
    double start = CACurrentMediaTime();
    while (task.isRunning && CACurrentMediaTime() - start < 7.5) usleep(50000);
    if (task.isRunning) { [task terminate]; return @{ @"variant": variant, @"error": @"timeout" }; }
    NSData *data = [NSData dataWithContentsOfFile:output];
    [[NSFileManager defaultManager] removeItemAtPath:output error:nil];
    id parsed = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
    return parsed ?: @{ @"variant": variant, @"error": @"no report", @"status": @(task.terminationStatus),
                        @"reason": @(task.terminationReason) };
}

// Child mode, run in the console user's session: a borderless window whose
// CAMetalLayer shows the test pattern for four seconds. Writes a JSON report.
static int windowChild(NSString *outputPath, unsigned long long expiry) {
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    void (^save)(void) = ^{
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        [data writeToFile:outputPath atomically:NO];
    };
    signal(SIGALRM, deadline);
    alarm(14);
    const double launchTime = CACurrentMediaTime();
    if ((unsigned long long)time(NULL) > expiry) { result[@"error"] = @"expired"; save(); return 1; }
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    if (!device) { result[@"error"] = @"no Metal device"; save(); return 1; }
    result[@"device"] = device.name;
    NSMutableDictionary *errors = [NSMutableDictionary dictionary];
    id<MTLLibrary> library = compileLibrary(device, kShaderSource, @"render", errors);
    id<MTLRenderPipelineState> pipeline = library ? renderPipeline(device, library, @"fullscreen", @"pattern") : nil;
    id<MTLCommandQueue> queue = [device newCommandQueue];
    result[@"shader_errors"] = errors;
    if (!pipeline || !queue) { result[@"error"] = @"pipeline"; save(); return 1; }

    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    [NSApp finishLaunching];
    NSScreen *screen = NSScreen.screens.firstObject;
    if (!screen) { result[@"error"] = @"no screen"; save(); return 1; }
    CGFloat screenHeight = screen.frame.size.height;
    NSRect frame = NSMakeRect(kWindowX, screenHeight - kWindowY - kWindowH, kWindowW, kWindowH);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:frame styleMask:NSWindowStyleMaskBorderless
                                                     backing:NSBackingStoreBuffered defer:NO];
    window.level = NSScreenSaverWindowLevel;
    window.opaque = YES;
    window.hasShadow = NO;
    window.releasedWhenClosed = NO;
    CGFloat scale = window.backingScaleFactor;
    CAMetalLayer *layer = [CAMetalLayer layer];
    layer.device = device;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    layer.framebufferOnly = NO;
    layer.contentsScale = scale;
    layer.drawableSize = CGSizeMake(kWindowW * scale, kWindowH * scale);
    CGColorSpaceRef srgb = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    layer.colorspace = srgb;
    CGColorSpaceRelease(srgb);
    NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, kWindowW, kWindowH)];
    view.layer = layer;
    view.wantsLayer = YES;
    window.contentView = view;
    [window orderFrontRegardless];
    [CATransaction flush];
    result[@"screen_height"] = @(screenHeight);
    result[@"backing_scale"] = @(scale);
    result[@"window_number"] = @(window.windowNumber);

    NSObject *lock = [[NSObject alloc] init];
    __block NSUInteger presented = 0, completedErrors = 0, presentedCallbacks = 0;
    NSMutableArray *selfCaptures = [NSMutableArray array];
    NSMutableArray *selfJpegs = [NSMutableArray array];
    CGImageRef (*windowImage)(CGRect, uint32_t, uint32_t, uint32_t) =
        (CGImageRef (*)(CGRect, uint32_t, uint32_t, uint32_t))dlsym(RTLD_DEFAULT, "CGWindowListCreateImage");
    id<MTLBuffer> drawableReadback = [device newBufferWithLength:(NSUInteger)(kWindowW * scale) *
                                                                 (NSUInteger)(kWindowH * scale) * 4
                                                         options:MTLResourceStorageModeShared];
    NSDictionary *drawableCheck = nil;
    __block double firstPresent = 0, lastPresent = 0;
    NSUInteger submitted = 0, missingDrawables = 0;
    id<MTLCommandBuffer> last = nil;
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    double start = CACurrentMediaTime();
    result[@"setup_seconds"] = @(start - launchTime);
    while (CACurrentMediaTime() - start < 4.0) {
        @autoreleasepool {
            NSEvent *event;
            while ((event = [NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate distantPast]
                                                  inMode:NSDefaultRunLoopMode dequeue:YES]))
                [NSApp sendEvent:event];
            id<CAMetalDrawable> drawable = [layer nextDrawable];
            if (!drawable) { ++missingDrawables; continue; }
            double t = CACurrentMediaTime() - start;
            float uniforms[4] = { (float)drawable.texture.width, (float)drawable.texture.height,
                                  (float)fmod(t / 2.0, 1.0), 0 };
            pass.colorAttachments[0].texture = drawable.texture;
            id<MTLCommandBuffer> command = [queue commandBuffer];
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
            [encoder setRenderPipelineState:pipeline];
            [encoder setFragmentBytes:uniforms length:sizeof(uniforms) atIndex:0];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            [encoder endEncoding];
            [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                CFTimeInterval when = shown.presentedTime;
                @synchronized (lock) { ++presentedCallbacks; }
                if (when <= 0) return;
                @synchronized (lock) {
                    ++presented;
                    if (firstPresent == 0) firstPresent = when;
                    lastPresent = when;
                }
            }];
            [command addCompletedHandler:^(id<MTLCommandBuffer> done) {
                if (done.status != MTLCommandBufferStatusCompleted) {
                    @synchronized (lock) { ++completedErrors; }
                }
            }];
            BOOL readThis = submitted == 20 && drawableReadback;
            if (readThis) {
                id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
                NSUInteger tw = drawable.texture.width, th = drawable.texture.height;
                [blit copyFromTexture:drawable.texture sourceSlice:0 sourceLevel:0
                         sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(tw, th, 1)
                             toBuffer:drawableReadback destinationOffset:0
               destinationBytesPerRow:tw * 4 destinationBytesPerImage:tw * th * 4];
                [blit endEncoding];
            }
            [command presentDrawable:drawable];
            [command commit];
            last = command;
            if (readThis) {
                [command waitUntilCompleted];
                NSUInteger tw = drawable.texture.width, th = drawable.texture.height;
                const UInt8 *px = drawableReadback.contents;
                struct { const char *name; double u, v; int r, g, b; } spots[] = {
                    { "top_left_red", 0.25, 0.22, 255, 0, 0 }, { "top_right_green", 0.75, 0.22, 0, 255, 0 },
                    { "bottom_left_blue", 0.25, 0.78, 0, 0, 255 }, { "bottom_right_white", 0.75, 0.78, 255, 255, 255 },
                };
                NSMutableDictionary *rows = [NSMutableDictionary dictionary];
                BOOL all = YES;
                for (size_t i = 0; i < 4; ++i) {
                    const UInt8 *q = px + ((NSUInteger)(th * spots[i].v) * tw + (NSUInteger)(tw * spots[i].u)) * 4;
                    BOOL match = q[2] == spots[i].r && q[1] == spots[i].g && q[0] == spots[i].b;
                    all &= match;
                    rows[@(spots[i].name)] = @[ @(q[2]), @(q[1]), @(q[0]), @(match) ];
                }
                NSUInteger wrongQuadrant = 0, checkedQuadrant = 0;
                for (NSUInteger y = 0; y < th; y += 3) {
                    double v = (y + 0.5) / th;
                    if (v > 0.44 && v < 0.56) continue;
                    for (NSUInteger x = 0; x < tw; x += 3) {
                        double u = (x + 0.5) / tw;
                        if (u > 0.49 && u < 0.51) continue;
                        const UInt8 *q = px + (y * tw + x) * 4;
                        int er = 0, eg = 0, eb = 0;
                        if (v <= 0.45) { if (u < 0.5) er = 255; else eg = 255; }
                        else if (u < 0.5) eb = 255; else { er = eg = eb = 255; }
                        ++checkedQuadrant;
                        wrongQuadrant += q[2] != er || q[1] != eg || q[0] != eb;
                    }
                }
                drawableCheck = @{ @"samples": rows, @"pattern_match": @(all),
                                   @"checked": @(checkedQuadrant), @"wrong": @(wrongQuadrant),
                                   @"width": @(tw), @"height": @(th) };
            }
            double elapsed = CACurrentMediaTime() - start;
            if (windowImage && ((selfCaptures.count == 0 && elapsed > 1.5) ||
                                (selfCaptures.count == 1 && elapsed > 2.5))) {
                CGImageRef shot = windowImage(CGRectNull, 8 /* IncludingWindow */,
                                              (uint32_t)window.windowNumber, 1 | 8 /* IgnoreFraming|Best */);
                NSString *label = selfCaptures.count == 0 ? @"self_1" : @"self_2";
                if (shot) {
                    size_t sw = CGImageGetWidth(shot), sh = CGImageGetHeight(shot);
                    NSDictionary *check = checkPatternRegion(shot, CGRectMake(0, 0, sw, sh), label, selfJpegs);
                    [selfCaptures addObject:check];
                    CGImageRelease(shot);
                } else {
                    [selfCaptures addObject:@{ @"label": label, @"captured": @NO }];
                }
            }
            if (++submitted == 10) {
                NSUInteger shown;
                @synchronized (lock) { shown = presented; }
                [@{ @"submitted": @(submitted), @"presented": @(shown),
                    @"seconds": @(CACurrentMediaTime() - start) }.description
                    writeToFile:[outputPath stringByAppendingString:@".ready"] atomically:NO
                       encoding:NSUTF8StringEncoding error:nil];
            }
        }
    }
    [last waitUntilCompleted];
    [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.3]];
    @synchronized (lock) {
        result[@"submitted_frames"] = @(submitted);
        result[@"presented_frames"] = @(presented);
        result[@"presented_callbacks"] = @(presentedCallbacks);
        result[@"missing_drawables"] = @(missingDrawables);
        result[@"failed_command_buffers"] = @(completedErrors);
        result[@"present_fps"] = @(presented > 1 && lastPresent > firstPresent ?
                                   (presented - 1) / (lastPresent - firstPresent) : 0);
        result[@"submit_seconds"] = @(CACurrentMediaTime() - start);
    }
    result[@"drawable_readback"] = drawableCheck ?: @{ @"error": @"not captured" };
    result[@"self_captures"] = selfCaptures;
    result[@"self_capture_symbol"] = @(windowImage != NULL);
    result[@"self_jpegs"] = selfJpegs;
    result[@"uid"] = @(getuid());
    [window orderOut:nil];
    [CATransaction flush];
    save();
    return 0;
}

static NSDictionary *checkPatternRegion(CGImageRef image, CGRect region, NSString *label, NSMutableArray *jpegs) {
    if (!image) return @{ @"label": label, @"captured": @NO };
    size_t width = 0, height = 0;
    NSData *pixels = regionPixels(image, region, &width, &height);
    if (!pixels) return @{ @"label": label, @"captured": @NO, @"reason": @"region" };
    const UInt8 *bytes = pixels.bytes;
    struct { const char *name; double u, v; int r, g, b; } probes[] = {
        { "top_left_red", 0.25, 0.22, 1, 0, 0 }, { "top_right_green", 0.75, 0.22, 0, 1, 0 },
        { "bottom_left_blue", 0.25, 0.78, 0, 0, 1 }, { "bottom_right_white", 0.75, 0.78, 1, 1, 1 },
    };
    NSMutableDictionary *samples = [NSMutableDictionary dictionary];
    BOOL allMatch = YES;
    for (size_t i = 0; i < sizeof(probes) / sizeof(probes[0]); ++i) {
        size_t x = (size_t)(width * probes[i].u), y = (size_t)(height * probes[i].v);
        const UInt8 *p = bytes + (y * width + x) * 4;
        NSArray *rgb = @[ @(p[0]), @(p[1]), @(p[2]) ];
        BOOL match = colorMatches(rgb, probes[i].r * 255, probes[i].g * 255, probes[i].b * 255);
        allMatch &= match;
        samples[@(probes[i].name)] = @{ @"rgb": rgb, @"match": @(match) };
    }
    // The moving bar: dark and gray pixels along the middle row, and where the dark run is.
    NSUInteger dark = 0, gray = 0;
    long darkFirst = -1, darkLast = -1;
    const UInt8 *row = bytes + (height / 2) * width * 4;
    for (size_t x = 0; x < width; ++x) {
        int r = row[x * 4], g = row[x * 4 + 1], b = row[x * 4 + 2];
        if (r < 40 && g < 40 && b < 40) {
            ++dark;
            if (darkFirst < 0) darkFirst = (long)x;
            darkLast = (long)x;
        } else if (abs(r - g) < 30 && abs(g - b) < 30 && r > 80 && r < 200) {
            ++gray;
        }
    }
    [jpegs addObject:jpegOf(image, region, 400, 0.85, label)];
    return @{ @"label": label, @"captured": @YES, @"width": @(width), @"height": @(height),
              @"samples": samples, @"pattern_match": @(allMatch),
              @"bar_dark_pixels": @(dark), @"bar_gray_pixels": @(gray),
              @"bar_dark_span": @[ @(darkFirst), @(darkLast) ],
              @"region_fnv": fnvHex(bytes, pixels.length) };
}

static NSDictionary *checkPattern(CGImageRef image, CGFloat pixelScale, NSString *label, NSMutableArray *jpegs) {
    CGRect region = CGRectMake(floor(kWindowX * pixelScale), floor(kWindowY * pixelScale),
                               floor(kWindowW * pixelScale), floor(kWindowH * pixelScale));
    return checkPatternRegion(image, region, label, jpegs);
}

static NSDictionary *windowTest(const char *selfPath, unsigned long long expiry, CGDirectDisplayID display,
                                NSMutableArray *jpegs) {
    pid_t pid = getpid();
    NSString *child = [NSString stringWithFormat:@"/var/tmp/rgpu-window-child-%d", pid];
    NSString *output = [NSString stringWithFormat:@"/var/tmp/rgpu-window-%d.json", pid];
    NSString *ready = [output stringByAppendingString:@".ready"];
    NSFileManager *files = [NSFileManager defaultManager];
    [files removeItemAtPath:child error:nil];
    [files removeItemAtPath:output error:nil];
    [files removeItemAtPath:ready error:nil];
    NSError *error = nil;
    if (![files copyItemAtPath:@(selfPath) toPath:child error:&error])
        return @{ @"error": [NSString stringWithFormat:@"copy: %@", error.localizedDescription] };
    chmod(child.fileSystemRepresentation, 0755);
    NSTask *task = [[NSTask alloc] init];
    task.launchPath = @"/bin/launchctl";
    task.arguments = @[ @"asuser", @"501", @"/usr/bin/sudo", @"-n", @"-u", @"#501", child,
                        @"--window-child", output, [NSString stringWithFormat:@"%llu", expiry] ];
    task.standardOutput = [NSFileHandle fileHandleWithNullDevice];
    task.standardError = [NSFileHandle fileHandleWithNullDevice];
    @try { [task launch]; }
    @catch (NSException *exception) { return @{ @"error": @"launch-failed" }; }
    CGImageRef imageSize = createDisplayImage(display);
    CGFloat pixelScale = imageSize ? (CGFloat)CGImageGetWidth(imageSize) / (CGFloat)CGDisplayPixelsWide(display) : 1;
    if (imageSize) CGImageRelease(imageSize);
    double launched = CACurrentMediaTime();
    while (task.isRunning && ![files fileExistsAtPath:ready] && CACurrentMediaTime() - launched < 8.0)
        usleep(50000);
    double readyAfter = CACurrentMediaTime() - launched;
    BOOL wasReady = [files fileExistsAtPath:ready];
    usleep(500000);
    CGImageRef first = createDisplayImage(display);
    usleep(1000000);
    CGImageRef second = createDisplayImage(display);
    while (task.isRunning && CACurrentMediaTime() - launched < 14.0) usleep(50000);
    BOOL timedOut = task.isRunning;
    if (timedOut) [task terminate];
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    result[@"pixel_scale"] = @(pixelScale);
    result[@"child_timed_out"] = @(timedOut);
    result[@"child_ready"] = @(wasReady);
    result[@"ready_after_seconds"] = @(readyAfter);
    NSString *readyText = [NSString stringWithContentsOfFile:ready encoding:NSUTF8StringEncoding error:nil];
    if (readyText) result[@"ready_marker"] = readyText;
    if (!timedOut) result[@"child_status"] = @(task.terminationStatus);
    NSData *childData = [NSData dataWithContentsOfFile:output];
    id childReport = childData ? [NSJSONSerialization JSONObjectWithData:childData options:0 error:nil] : nil;
    result[@"child"] = childReport ?: @{ @"error": @"no report" };
    NSDictionary *a = checkPattern(first, pixelScale, @"window_1", jpegs);
    NSDictionary *b = checkPattern(second, pixelScale, @"window_2", jpegs);
    result[@"captures"] = @[ a, b ];
    result[@"pattern_ok"] = @([a[@"pattern_match"] boolValue] && [b[@"pattern_match"] boolValue]);
    result[@"window_frames_changed"] = @([a[@"captured"] boolValue] && [b[@"captured"] boolValue] &&
                                         ![a[@"region_fnv"] isEqual:b[@"region_fnv"]]);
    if (first) CGImageRelease(first);
    if (second) CGImageRelease(second);
    [files removeItemAtPath:child error:nil];
    [files removeItemAtPath:output error:nil];
    [files removeItemAtPath:ready error:nil];
    return result;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc == 4 && strcmp(argv[1], "--window-child") == 0)
            return windowChild(@(argv[2]), strtoull(argv[3], NULL, 10));
        if (argc == 4 && strcmp(argv[1], "--render-child") == 0)
            return renderChild(@(argv[2]), strtoull(argv[3], NULL, 10));
        if (argc == 5 && strcmp(argv[1], "--patch-child") == 0)
            return patchChild(@(argv[2]), @(argv[3]), strtoull(argv[4], NULL, 10));
        signal(SIGALRM, deadline);
        alarm(45);
        report = [@{ @"run_id": argc > 1 ? @(argv[1]) : @"manual", @"passed": @NO,
                     @"completed_command_buffers": @0, @"values_checked": @0,
                     @"probe_version": @7 } mutableCopy];
        char *end = NULL;
        unsigned long long expiry = argc == 3 ? strtoull(argv[2], &end, 10) : 0;
        if (argc != 3 || end == NULL || *end != '\0' || (unsigned long long)time(NULL) > expiry)
            fail(@"invalid or expired run permit");

        id<MTLDevice> device = MTLCreateSystemDefaultDevice();
        if (!device) fail(@"no Metal device");
        report[@"device"] = device.name;
        report[@"registry_id"] = @(device.registryID);
        report[@"metal3"] = @([device supportsFamily:MTLGPUFamilyMetal3]);

        NSMutableDictionary *shaderErrors = [NSMutableDictionary dictionary];
        report[@"shader_errors"] = shaderErrors;
        NSError *error = nil;
        id<MTLLibrary> computeLibrary = compileLibrary(device, kComputeSource, @"compute", shaderErrors);
        id<MTLFunction> function = [computeLibrary newFunctionWithName:@"mix"];
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
        // From here on, the pass is decided; later evidence only adds fields.
        report[@"passed"] = @YES;

        CGDirectDisplayID displays[16];
        uint32_t displayCount = 0;
        NSMutableArray *displayRows = [NSMutableArray array];
        BOOL displayOnDevice = NO;
        if (CGGetActiveDisplayList(16, displays, &displayCount) == kCGErrorSuccess) {
            for (uint32_t i = 0; i < displayCount; ++i) {
                id<MTLDevice> displayDevice = CGDirectDisplayCopyCurrentMetalDevice(displays[i]);
                BOOL same = displayDevice && displayDevice.registryID == device.registryID;
                displayOnDevice |= same;
                NSMutableDictionary *row = [@{ @"id": @(displays[i]),
                                               @"width": @(CGDisplayPixelsWide(displays[i])),
                                               @"height": @(CGDisplayPixelsHigh(displays[i])),
                                               @"main": @(CGDisplayIsMain(displays[i]) != 0),
                                               @"metal_device": displayDevice ? displayDevice.name : @"none",
                                               @"same_device": @(same),
                                               @"vendor": @(CGDisplayVendorNumber(displays[i])),
                                               @"model": @(CGDisplayModelNumber(displays[i])),
                                               @"serial": @(CGDisplaySerialNumber(displays[i])),
                                               @"builtin": @(CGDisplayIsBuiltin(displays[i]) != 0) } mutableCopy];
                CGDisplayModeRef mode = CGDisplayCopyDisplayMode(displays[i]);
                if (mode) {
                    row[@"refresh_hz"] = @(CGDisplayModeGetRefreshRate(mode));
                    row[@"mode_pixels"] = @[ @(CGDisplayModeGetPixelWidth(mode)), @(CGDisplayModeGetPixelHeight(mode)) ];
                    CGDisplayModeRelease(mode);
                }
                CFArrayRef modes = CGDisplayCopyAllDisplayModes(displays[i], NULL);
                if (modes) {
                    row[@"mode_count"] = @(CFArrayGetCount(modes));
                    CFRelease(modes);
                }
                [displayRows addObject:row];
            }
        }
        report[@"displays"] = displayRows;
        report[@"display_on_device"] = @(displayOnDevice);
        report[@"framebuffers"] = framebufferEvidence();
        BOOL windowServerClient = NO;
        report[@"accelerators"] = acceleratorEvidence(device.registryID, &windowServerClient);
        report[@"windowserver_accelerator_client"] = @(windowServerClient);
        report[@"screen_capture_preflight"] = @(CGPreflightScreenCaptureAccess());

        id<MTLLibrary> library = compileLibrary(device, kShaderSource, @"render", shaderErrors);
        id<MTLLibrary> identityLibrary = compileLibrary(device, kIdentitySource, @"identity", shaderErrors);
        if (library) report[@"offscreen"] = offscreenThroughput(device, library, queue);

        NSMutableArray *readback = [NSMutableArray array];
        [readback addObjectsFromArray:readbackMatrix(device, identityLibrary, queue, 64, 64,
                                                     MTLClearColorMake(0.25, 0.25, 0.25, 0.25))];
        [readback addObjectsFromArray:readbackMatrix(device, identityLibrary, queue, 1280, 1024,
                                                     MTLClearColorMake(0, 0, 0, 0))];
        report[@"readback_matrix"] = readback;
        report[@"patch_children"] = @[ patchChildRun(argv[0], expiry, @"pipebankxor0"),
                                       patchChildRun(argv[0], expiry, @"blitdma0"),
                                       patchChildRun(argv[0], expiry, @"linearswizzle1") ];

        NSMutableArray *jpegs = [NSMutableArray array];
        if (displayCount > 0) {
            CGImageRef desktop = createDisplayImage(CGMainDisplayID());
            report[@"desktop_capture"] = imageSummary(desktop);
            [jpegs addObject:jpegOf(desktop, CGRectNull, 640, 0.7, @"desktop")];
            if (desktop) CGImageRelease(desktop);
            report[@"window_test"] = windowTest(argv[0], expiry, CGMainDisplayID(), jpegs);
            CGImageRef after = createDisplayImage(CGMainDisplayID());
            report[@"desktop_after_capture"] = imageSummary(after);
            if (after) CGImageRelease(after);
        }
        report[@"jpegs"] = jpegs;
        emit();
    }
    return 0;
}
