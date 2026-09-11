#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <QuartzCore/CAMetalLayer.h>
#import <SystemConfiguration/SystemConfiguration.h>
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <signal.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width height:(unsigned int)height
                   refreshRate:(double)refreshRate;
@end

@interface CGVirtualDisplaySettings : NSObject
@property(copy) NSArray *modes;
@property unsigned int hiDPI;
@property unsigned int rotation;
@end

@interface CGVirtualDisplayDescriptor : NSObject
@property unsigned int vendorID, productID, serialNum, maxPixelsWide, maxPixelsHigh;
@property(copy) NSString *name;
@property CGSize sizeInMillimeters;
@property CGPoint redPrimary, greenPrimary, bluePrimary, whitePoint;
@property(strong) id queue;
@property(copy) id terminationHandler;
@property unsigned int serialNumber;
@end

@interface CGVirtualDisplay : NSObject
@property(readonly) CGDirectDisplayID displayID;
- (instancetype)initWithDescriptor:(id)descriptor;
- (BOOL)applySettings:(id)settings;
@end

static volatile sig_atomic_t stopSignal = 0;

static void requestStop(int signalNumber) {
    stopSignal = signalNumber;
}

static BOOL validHex(NSString *value, NSUInteger length) {
    if (value.length != length) return NO;
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:
        @"0123456789abcdef"] invertedSet];
    return [value rangeOfCharacterFromSet:invalid].location == NSNotFound;
}

static BOOL parseUnsigned(const char *text, unsigned long long *value) {
    if (!text || !*text || text[0] == '-') return NO;
    errno = 0;
    char *end = NULL;
    unsigned long long parsed = strtoull(text, &end, 10);
    if (errno != 0 || !end || *end != '\0') return NO;
    *value = parsed;
    return YES;
}

static NSArray<NSNumber *> *onlineDisplayIDs(CGError *errorOut) {
    CGDirectDisplayID ids[64] = {};
    uint32_t count = 0;
    CGError error = CGGetOnlineDisplayList(64, ids, &count);
    if (errorOut) *errorOut = error;
    if (error != kCGErrorSuccess) return nil;
    NSMutableArray<NSNumber *> *result = [NSMutableArray arrayWithCapacity:count];
    for (uint32_t index = 0; index < count; ++index) [result addObject:@(ids[index])];
    [result sortUsingSelector:@selector(compare:)];
    return result;
}

static NSArray<NSNumber *> *newDisplayIDs(NSArray<NSNumber *> *baseline,
                                           NSArray<NSNumber *> *current) {
    NSMutableSet<NSNumber *> *old = [NSMutableSet setWithArray:baseline ?: @[]];
    NSMutableArray<NSNumber *> *added = [NSMutableArray array];
    for (NSNumber *displayID in current ?: @[])
        if (![old containsObject:displayID]) [added addObject:displayID];
    [added sortUsingSelector:@selector(compare:)];
    return added;
}

static id<MTLDevice> deviceWithRegistryID(uint64_t registryID) {
    for (id<MTLDevice> device in MTLCopyAllDevices())
        if (device.registryID == registryID) return device;
    return nil;
}

static NSScreen *screenWithDisplayID(CGDirectDisplayID displayID) {
    for (NSScreen *screen in [NSScreen screens]) {
        NSNumber *number = screen.deviceDescription[@"NSScreenNumber"];
        if (number.unsignedIntValue == displayID) return screen;
    }
    return nil;
}

static NSDictionary *aquaFacts(void) {
    uid_t consoleUID = 0;
    gid_t consoleGID = 0;
    NSString *consoleUser = CFBridgingRelease(
        SCDynamicStoreCopyConsoleUser(NULL, &consoleUID, &consoleGID)) ?: @"";
    (void)consoleGID;
    NSDictionary *session = CFBridgingRelease(CGSessionCopyCurrentDictionary());
    NSNumber *sessionUID = session[(__bridge NSString *)kCGSessionUserIDKey];
    NSString *sessionUser = session[(__bridge NSString *)kCGSessionUserNameKey];
    NSNumber *loginDone = session[(__bridge NSString *)kCGSessionLoginDoneKey];
    NSNumber *onConsole = session[(__bridge NSString *)kCGSessionOnConsoleKey];
    NSString *actualDomain = [[[NSProcessInfo processInfo] environment]
        objectForKey:@"RGPU_LAUNCH_DOMAIN"] ?: @"";
    NSString *expectedDomain = [NSString stringWithFormat:@"gui/%u", getuid()];
    BOOL environmentMatches = [actualDomain isEqualToString:expectedDomain];
    BOOL ready = (getuid() >= 500 && consoleUID == getuid() &&
                  [consoleUser isEqualToString:sessionUser] &&
                  sessionUID.unsignedIntValue == getuid() && loginDone.boolValue &&
                  onConsole.boolValue && environmentMatches);
    return @{
        @"ready": @((BOOL)ready),
        @"console_user": consoleUser,
        @"console_uid": @(consoleUID),
        @"session_user": [sessionUser isKindOfClass:[NSString class]] ? sessionUser : @"",
        @"session_uid": [sessionUID isKindOfClass:[NSNumber class]] ? sessionUID : @0,
        @"login_done": @((BOOL)loginDone.boolValue),
        @"on_console": @((BOOL)onConsole.boolValue),
        @"launch_domain": expectedDomain,
        @"launch_domain_environment": @((BOOL)environmentMatches),
        @"launchd_job_pid": @((int)getpid()),
    };
}

static BOOL writeReceipt(NSDictionary *receipt, NSString *path) {
    NSError *error = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:receipt options:0 error:&error];
    if (!json || error) return NO;
    NSMutableData *line = [NSMutableData data];
    [line appendData:[@"RGPU_DESKTOP_RESULT " dataUsingEncoding:NSUTF8StringEncoding]];
    [line appendData:json];
    [line appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    // Atomic writes are sufficient here; Foundation rejects combining this
    // option with NSDataWritingWithoutOverwriting.
    return [line writeToFile:path options:NSDataWritingAtomic error:&error];
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 9) return 2;
        NSString *executionMode = [NSString stringWithUTF8String:argv[1]];
        BOOL production = [executionMode isEqualToString:@"production"];
        BOOL qualification = [executionMode isEqualToString:@"gpuless-qualification"];
        NSString *nonce = [NSString stringWithUTF8String:argv[2]];
        NSString *outputPath = [NSString stringWithUTF8String:argv[6]];
        NSString *sourceSHA = [NSString stringWithUTF8String:argv[7]];
        NSString *binarySHA = [NSString stringWithUTF8String:argv[8]];
        unsigned long long expiryRaw = 0, holdRaw = 0, registryRaw = 0;
        if ((!production && !qualification) || !validHex(nonce, 32) ||
            !validHex(sourceSHA, 64) ||
            !validHex(binarySHA, 64) ||
            !parseUnsigned(argv[3], &expiryRaw) ||
            !parseUnsigned(argv[4], &holdRaw) || holdRaw < 1 || holdRaw > 30 ||
            !parseUnsigned(argv[5], &registryRaw) ||
            (production && registryRaw == 0) || (qualification && registryRaw != 0) ||
            outputPath.length == 0 || expiryRaw > (unsigned long long)LLONG_MAX)
            return 2;

        signal(SIGHUP, requestStop);
        signal(SIGINT, requestStop);
        signal(SIGTERM, requestStop);
        signal(SIGALRM, requestStop);
        alarm((unsigned int)holdRaw + 9);

        time_t started = time(NULL);
        NSDictionary *aqua = aquaFacts();
        CGError baselineError = kCGErrorSuccess;
        NSArray<NSNumber *> *baseline = onlineDisplayIDs(&baselineError);
        NSArray<NSNumber *> *newIDs = @[];
        NSArray<NSNumber *> *finalIDs = baseline ?: @[];
        BOOL created = NO, applied = NO, added = NO, active = NO, removed = NO;
        BOOL cleanupComplete = NO, windowVisible = NO;
        CGDirectDisplayID windowDisplayID = 0;
        CGDirectDisplayID displayID = 0;
        size_t width = 0, height = 0;
        double refresh = 0;
        NSUInteger acquired = 0, submitted = 0, completed = 0, presented = 0;
        NSUInteger firstFrame = 0, lastFrame = 0;
        BOOL usedColors[8] = {};
        NSUInteger distinctColors = 0;
        NSString *firstColor = @"";
        NSString *lastColor = @"";
        NSString *deviceName = @"";
        CGVirtualDisplay *display = nil;
        NSWindow *window = nil;
        CAMetalLayer *metalLayer = nil;

        BOOL admitted = (started > 0 && (unsigned long long)started <= expiryRaw &&
                         expiryRaw - (unsigned long long)started >= holdRaw + 8 &&
                         [aqua[@"ready"] boolValue] &&
                         baselineError == kCGErrorSuccess);
        id<MTLDevice> device = admitted && production ? deviceWithRegistryID(registryRaw) : nil;
        deviceName = device.name ?: @"";
        id<MTLCommandQueue> queue = device ? [device newCommandQueue] : nil;

        if (admitted && (qualification || (device && queue))) {
            [NSApplication sharedApplication];
            [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
            [NSApp finishLaunching];
            unsigned int serial = 0;
            [[NSScanner scannerWithString:[nonce substringToIndex:8]] scanHexInt:&serial];
            if (serial == 0) serial = 1;
            CGVirtualDisplayDescriptor *descriptor = [CGVirtualDisplayDescriptor new];
            descriptor.queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0);
            descriptor.name = @"Raphael bounded desktop display";
            descriptor.whitePoint = CGPointMake(0.3125, 0.3291);
            descriptor.bluePrimary = CGPointMake(0.1494, 0.0557);
            descriptor.greenPrimary = CGPointMake(0.2559, 0.6983);
            descriptor.redPrimary = CGPointMake(0.6797, 0.3203);
            descriptor.maxPixelsHigh = 720;
            descriptor.maxPixelsWide = 1280;
            descriptor.sizeInMillimeters = CGSizeMake(25.4 * 1280 / 100,
                                                       25.4 * 720 / 100);
            descriptor.serialNum = serial;
            descriptor.serialNumber = serial;
            descriptor.productID = 0;
            descriptor.vendorID = 505;
            descriptor.terminationHandler = nil;
            display = [[CGVirtualDisplay alloc] initWithDescriptor:descriptor];
            created = display != nil;
            if (display) {
                displayID = display.displayID;
                CGVirtualDisplayMode *mode = [[CGVirtualDisplayMode alloc]
                    initWithWidth:1280 height:720 refreshRate:60.0];
                CGVirtualDisplaySettings *settings = [CGVirtualDisplaySettings new];
                if (mode) {
                    settings.modes = @[mode];
                    settings.hiDPI = 0;
                    settings.rotation = 0;
                    applied = [display applySettings:settings];
                }
                for (NSUInteger attempt = 0; attempt < 40 && !added && !stopSignal;
                     ++attempt) {
                    NSArray<NSNumber *> *current = onlineDisplayIDs(NULL);
                    newIDs = newDisplayIDs(baseline, current);
                    added = (newIDs.count == 1 &&
                             newIDs.firstObject.unsignedIntValue == displayID);
                    active = added && CGDisplayIsActive(displayID) != 0;
                    CGDisplayModeRef currentMode = added ?
                        CGDisplayCopyDisplayMode(displayID) : NULL;
                    if (currentMode) {
                        width = CGDisplayModeGetWidth(currentMode);
                        height = CGDisplayModeGetHeight(currentMode);
                        refresh = CGDisplayModeGetRefreshRate(currentMode);
                        CFRelease(currentMode);
                    }
                    added = added && active && width == 1280 && height == 720 &&
                            fabs(refresh - 60.0) <= 0.01;
                    if (!added) {
                        [[NSRunLoop currentRunLoop]
                            runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
                    }
                }
            }
        }

        if (added && !stopSignal) {
            NSScreen *ownedScreen = nil;
            for (NSUInteger attempt = 0; attempt < 40 && !ownedScreen && !stopSignal;
                 ++attempt) {
                ownedScreen = screenWithDisplayID(displayID);
                if (!ownedScreen) {
                    [[NSRunLoop currentRunLoop]
                        runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
                }
            }
            if (ownedScreen) {
                window = [[NSWindow alloc] initWithContentRect:ownedScreen.frame
                    styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
                window.opaque = YES;
                window.backgroundColor = [NSColor blackColor];
                window.level = NSScreenSaverWindowLevel;
                window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                            NSWindowCollectionBehaviorFullScreenAuxiliary;
                NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 1280, 720)];
                view.wantsLayer = YES;
                if (production) {
                    metalLayer = [CAMetalLayer layer];
                    metalLayer.device = device;
                    metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
                    metalLayer.framebufferOnly = YES;
                    metalLayer.allowsNextDrawableTimeout = YES;
                    metalLayer.drawableSize = CGSizeMake(1280, 720);
                    metalLayer.frame = view.bounds;
                    view.layer = metalLayer;
                } else {
                    view.layer = [CALayer layer];
                    view.layer.backgroundColor = [NSColor redColor].CGColor;
                }
                window.contentView = view;
                [window orderFrontRegardless];
                [NSApp activateIgnoringOtherApps:YES];
                NSNumber *number = window.screen.deviceDescription[@"NSScreenNumber"];
                windowDisplayID = number.unsignedIntValue;
                windowVisible = window.visible && windowDisplayID == displayID;
            }

            if (windowVisible && production) {
              struct timespec holdStart = {};
              clock_gettime(CLOCK_MONOTONIC, &holdStart);
              double holdEnd = (double)holdStart.tv_sec +
                  (double)holdStart.tv_nsec / 1000000000.0 + (double)holdRaw;
              for (NSUInteger frameIndex = 0; !stopSignal; ++frameIndex) {
                time_t now = time(NULL);
                struct timespec current = {};
                clock_gettime(CLOCK_MONOTONIC, &current);
                double monotonic = (double)current.tv_sec +
                    (double)current.tv_nsec / 1000000000.0;
                double elapsed = (double)(current.tv_sec - holdStart.tv_sec) +
                    (double)(current.tv_nsec - holdStart.tv_nsec) / 1000000000.0;
                if (elapsed >= (double)holdRaw || now < 0 ||
                    (unsigned long long)now >= expiryRaw) break;
                @autoreleasepool {
                    id<CAMetalDrawable> drawable = [metalLayer nextDrawable];
                    if (drawable) {
                        acquired++;
                        BOOL secondPhase = elapsed >= (double)holdRaw / 2.0;
                        NSUInteger color = secondPhase ? 1 : 0;
                        if (!usedColors[color]) {
                            usedColors[color] = YES;
                            distinctColors++;
                        }
                        double red = secondPhase ? 0.0 : 1.0;
                        double green = secondPhase ? 1.0 : 0.0;
                        double blue = secondPhase ? 1.0 : 0.0;
                        NSString *colorToken = secondPhase ? @"#00ffff" : @"#ff0000";
                        MTLRenderPassDescriptor *pass =
                            [MTLRenderPassDescriptor renderPassDescriptor];
                        pass.colorAttachments[0].texture = drawable.texture;
                        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
                        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
                        pass.colorAttachments[0].clearColor = MTLClearColorMake(red, green, blue, 1);
                        id<MTLCommandBuffer> commandBuffer = [queue commandBuffer];
                        id<MTLRenderCommandEncoder> encoder =
                            [commandBuffer renderCommandEncoderWithDescriptor:pass];
                        [encoder endEncoding];
                        dispatch_semaphore_t commandDone = dispatch_semaphore_create(0);
                        dispatch_semaphore_t drawablePresented = dispatch_semaphore_create(0);
                        __block CFTimeInterval actualPresentedTime = 0;
                        [commandBuffer addCompletedHandler:^(id<MTLCommandBuffer> buffer) {
                            (void)buffer;
                            dispatch_semaphore_signal(commandDone);
                        }];
                        [drawable addPresentedHandler:^(id<MTLDrawable> item) {
                            actualPresentedTime = item.presentedTime;
                            dispatch_semaphore_signal(drawablePresented);
                        }];
                        [commandBuffer presentDrawable:drawable];
                        struct timespec beforeCommit = {};
                        clock_gettime(CLOCK_MONOTONIC, &beforeCommit);
                        double beforeCommitTime = (double)beforeCommit.tv_sec +
                            (double)beforeCommit.tv_nsec / 1000000000.0;
                        if (stopSignal || time(NULL) >= (time_t)expiryRaw ||
                            beforeCommitTime >= holdEnd) break;
                        [commandBuffer commit];
                        submitted++;
                        double commandDeadline = fmin(monotonic + 1.0, holdEnd);
                        BOOL commandAcknowledged = NO;
                        while (!stopSignal && time(NULL) < (time_t)expiryRaw) {
                            if (dispatch_semaphore_wait(commandDone,
                                                        DISPATCH_TIME_NOW) == 0) {
                                commandAcknowledged = YES;
                                break;
                            }
                            struct timespec poll = {};
                            clock_gettime(CLOCK_MONOTONIC, &poll);
                            double pollTime = (double)poll.tv_sec +
                                (double)poll.tv_nsec / 1000000000.0;
                            if (pollTime >= commandDeadline) break;
                            [[NSRunLoop currentRunLoop]
                                runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
                        }
                        BOOL commandCompleted = commandAcknowledged &&
                            commandBuffer.status == MTLCommandBufferStatusCompleted;
                        if (commandCompleted) completed++;
                        double presentationDeadline = fmin(commandDeadline + 1.0, holdEnd);
                        BOOL presentationAcknowledged = NO;
                        while (commandCompleted && !stopSignal &&
                               time(NULL) < (time_t)expiryRaw) {
                            if (dispatch_semaphore_wait(drawablePresented,
                                                        DISPATCH_TIME_NOW) == 0) {
                                presentationAcknowledged = YES;
                                break;
                            }
                            struct timespec poll = {};
                            clock_gettime(CLOCK_MONOTONIC, &poll);
                            double pollTime = (double)poll.tv_sec +
                                (double)poll.tv_nsec / 1000000000.0;
                            if (pollTime >= presentationDeadline) break;
                            [[NSRunLoop currentRunLoop]
                                runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.01]];
                        }
                        if (commandCompleted && presentationAcknowledged &&
                            actualPresentedTime > 0) {
                            if (presented == 0) {
                                firstFrame = frameIndex;
                                firstColor = colorToken;
                            }
                            lastFrame = frameIndex;
                            lastColor = colorToken;
                            presented++;
                        }
                        if (!commandCompleted || !presentationAcknowledged ||
                            actualPresentedTime <= 0) break;
                    }
                }
                  [[NSRunLoop currentRunLoop]
                      runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
              }
            } else if (windowVisible && qualification) {
                struct timespec holdStart = {};
                clock_gettime(CLOCK_MONOTONIC, &holdStart);
                while (!stopSignal && time(NULL) < (time_t)expiryRaw) {
                    struct timespec current = {};
                    clock_gettime(CLOCK_MONOTONIC, &current);
                    double elapsed = (double)(current.tv_sec - holdStart.tv_sec) +
                        (double)(current.tv_nsec - holdStart.tv_nsec) / 1000000000.0;
                    if (elapsed >= (double)holdRaw) break;
                    window.contentView.layer.backgroundColor =
                        (elapsed >= (double)holdRaw / 2.0 ?
                         [NSColor cyanColor] : [NSColor redColor]).CGColor;
                    [[NSRunLoop currentRunLoop]
                        runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
                }
            }
        }

        [window orderOut:nil];
        metalLayer = nil;
        window = nil;
        display = nil;
        for (NSUInteger attempt = 0; attempt < 40; ++attempt) {
            finalIDs = onlineDisplayIDs(NULL);
            removed = finalIDs && ![finalIDs containsObject:@(displayID)];
            cleanupComplete = finalIDs && [finalIDs isEqualToArray:baseline];
            if (removed && cleanupComplete) break;
            [[NSRunLoop currentRunLoop]
                runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }
        time_t finished = time(NULL);
        NSDictionary *displayFacts = @{
            @"baseline_ids": baseline ?: @[],
            @"created": @((BOOL)created),
            @"display_id": @(displayID),
            @"new_ids": newIDs ?: @[],
            @"settings_applied": @((BOOL)applied),
            @"added": @((BOOL)added),
            @"active": @((BOOL)active),
            @"width": @(width), @"height": @(height), @"refresh": @(refresh),
            @"removed": @((BOOL)removed), @"final_ids": finalIDs ?: @[],
            @"cleanup_complete": @((BOOL)cleanupComplete),
            @"termination_signal": @((int)stopSignal),
        };
        NSDictionary *stimulus = @{
            @"registry_id": @(registryRaw), @"device_name": deviceName,
            @"window_visible": @((BOOL)windowVisible),
            @"window_display_id": @(windowDisplayID),
            @"drawables_acquired": @(acquired),
            @"command_buffers_submitted": @(submitted),
            @"command_buffers_completed": @(completed),
            @"presented_frames": @(presented),
            @"first_frame": @(firstFrame), @"last_frame": @(lastFrame),
            @"distinct_color_tokens": @(distinctColors),
            @"first_color_token": firstColor, @"last_color_token": lastColor,
            @"classification": production ? @"selected_metal_device" :
                @"non_gpu_qualification",
        };
        NSDictionary *receipt = @{
            @"schema": @1, @"nonce": nonce, @"execution_mode": executionMode,
            @"source_sha256": sourceSHA, @"binary_sha256": binarySHA,
            @"guest_binary": [NSString stringWithUTF8String:argv[0]],
            @"expiry_epoch": @(expiryRaw), @"started_epoch": @(started),
            @"finished_epoch": @(finished), @"hold_seconds": @(holdRaw),
            @"aqua": aqua, @"display": displayFacts, @"stimulus": stimulus,
            @"remote_observation": @{
                @"required": @(production), @"observed": @NO,
                @"frame_change_observed": @NO,
                @"evidence": production ? @"external_capture_required" :
                    @"not_requested_gpuless_qualification",
            },
        };
        alarm(0);
        BOOL wrote = writeReceipt(receipt, outputPath);
        BOOL stimulusSuccess = qualification ||
            (acquired >= 2 && submitted >= 2 && completed >= 2 && presented >= 2 &&
             distinctColors >= 2 && [firstColor isEqualToString:@"#ff0000"] &&
             [lastColor isEqualToString:@"#00ffff"]);
        BOOL success = ([aqua[@"ready"] boolValue] && created && applied && added && active &&
                        windowVisible && stimulusSuccess && removed && cleanupComplete &&
                        finished > 0 && (unsigned long long)finished <= expiryRaw);
        if (stopSignal == SIGALRM) return 124;
        return wrote && success ? 0 : 1;
    }
}
