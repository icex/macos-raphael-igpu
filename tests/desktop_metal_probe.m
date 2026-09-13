// Desktop evidence probe: one small compute check on the Metal device, then evidence
// that the macOS desktop uses the same device and renders correctly:
// - which Metal device drives each active display, with display identity and the
//   framebuffer registry entries behind it;
// - which processes (WindowServer in particular) hold IOAccelerator user clients;
// - offscreen render throughput with a readback check of the rendered pixels;
// - a borderless CAMetalLayer window in the console user's session drawing a known
//   color pattern with a moving bar, checked pixel by pixel in the root display
//   capture, with its presentation rate;
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

static NSString *const kShaderSource =
    @"#include <metal_stdlib>\nusing namespace metal;\n"
     "struct V { float4 p [[position]]; };\n"
     "kernel void mix(device uint &v [[buffer(0)]], constant uint &s [[buffer(1)]]) { v ^= s; }\n"
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

static id<MTLRenderPipelineState> renderPipeline(id<MTLDevice> device, id<MTLLibrary> library,
                                                NSString *vertex, NSString *fragment) {
    MTLRenderPipelineDescriptor *descriptor = [[MTLRenderPipelineDescriptor alloc] init];
    descriptor.vertexFunction = [library newFunctionWithName:vertex];
    descriptor.fragmentFunction = [library newFunctionWithName:fragment];
    descriptor.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    if (!descriptor.vertexFunction || !descriptor.fragmentFunction) return nil;
    return [device newRenderPipelineStateWithDescriptor:descriptor error:nil];
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
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithSource:kShaderSource options:nil error:&error];
    id<MTLRenderPipelineState> pipeline = library ? renderPipeline(device, library, @"fullscreen", @"pattern") : nil;
    id<MTLCommandQueue> queue = [device newCommandQueue];
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
    layer.framebufferOnly = YES;
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
    __block NSUInteger presented = 0, completedErrors = 0;
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
            [command presentDrawable:drawable];
            [command commit];
            last = command;
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
        result[@"missing_drawables"] = @(missingDrawables);
        result[@"failed_command_buffers"] = @(completedErrors);
        result[@"present_fps"] = @(presented > 1 && lastPresent > firstPresent ?
                                   (presented - 1) / (lastPresent - firstPresent) : 0);
        result[@"submit_seconds"] = @(CACurrentMediaTime() - start);
    }
    [window orderOut:nil];
    [CATransaction flush];
    save();
    return 0;
}

static NSDictionary *checkPattern(CGImageRef image, CGFloat pixelScale, NSString *label, NSMutableArray *jpegs) {
    if (!image) return @{ @"label": label, @"captured": @NO };
    CGRect region = CGRectMake(floor(kWindowX * pixelScale), floor(kWindowY * pixelScale),
                               floor(kWindowW * pixelScale), floor(kWindowH * pixelScale));
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
    task.arguments = @[ @"asuser", @"501", child, @"--window-child", output,
                        [NSString stringWithFormat:@"%llu", expiry] ];
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
        signal(SIGALRM, deadline);
        alarm(45);
        report = [@{ @"run_id": argc > 1 ? @(argv[1]) : @"manual", @"passed": @NO,
                     @"completed_command_buffers": @0, @"values_checked": @0,
                     @"probe_version": @4 } mutableCopy];
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
        id<MTLLibrary> library = [device newLibraryWithSource:kShaderSource options:nil error:&error];
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

        report[@"offscreen"] = offscreenThroughput(device, library, queue);

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
