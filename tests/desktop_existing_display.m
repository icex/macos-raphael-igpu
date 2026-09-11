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
#include <time.h>
#include <unistd.h>

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

static BOOL parsePositiveDouble(const char *text, double *value) {
    if (!text || !*text || text[0] == '-') return NO;
    errno = 0;
    char *end = NULL;
    double parsed = strtod(text, &end);
    if (errno != 0 || !end || *end != '\0' || !isfinite(parsed) || parsed <= 0)
        return NO;
    *value = parsed;
    return YES;
}

static double monotonicNow(void) {
    struct timespec value = {};
    clock_gettime(CLOCK_MONOTONIC, &value);
    return (double)value.tv_sec + (double)value.tv_nsec / 1000000000.0;
}

static void pumpRunLoop(double seconds) {
    [[NSRunLoop currentRunLoop]
        runUntilDate:[NSDate dateWithTimeIntervalSinceNow:seconds]];
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

static NSArray<NSNumber *> *screenDisplayIDs(void) {
    NSMutableArray<NSNumber *> *result = [NSMutableArray array];
    for (NSScreen *screen in NSScreen.screens) {
        NSNumber *number = screen.deviceDescription[@"NSScreenNumber"];
        if ([number isKindOfClass:NSNumber.class]) [result addObject:number];
    }
    [result sortUsingSelector:@selector(compare:)];
    return result;
}

static id<MTLDevice> exactDevice(uint64_t registryID) {
    for (id<MTLDevice> device in MTLCopyAllDevices())
        if (device.registryID == registryID) return device;
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
    NSString *actualDomain = NSProcessInfo.processInfo.environment[@"RGPU_LAUNCH_DOMAIN"] ?: @"";
    NSString *expectedDomain = [NSString stringWithFormat:@"gui/%u", getuid()];
    BOOL domainMatches = [actualDomain isEqualToString:expectedDomain];
    BOOL ready = (getuid() >= 500 && consoleUID == getuid() &&
                  [consoleUser isEqualToString:sessionUser] &&
                  sessionUID.unsignedIntValue == getuid() && loginDone.boolValue &&
                  onConsole.boolValue && domainMatches);
    return @{
        @"ready": @((BOOL)ready), @"console_user": consoleUser,
        @"console_uid": @(consoleUID),
        @"session_user": [sessionUser isKindOfClass:NSString.class] ? sessionUser : @"",
        @"session_uid": [sessionUID isKindOfClass:NSNumber.class] ? sessionUID : @0,
        @"login_done": @((BOOL)loginDone.boolValue),
        @"on_console": @((BOOL)onConsole.boolValue),
        @"launch_domain": expectedDomain,
        @"launch_domain_environment": @((BOOL)domainMatches),
        @"launchd_job_pid": @((int)getpid()),
    };
}

static BOOL writeReceipt(NSDictionary *receipt, NSString *path) {
    NSError *error = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:receipt options:0 error:&error];
    if (!json || error) return NO;
    NSMutableData *line = [NSMutableData data];
    [line appendData:[@"RGPU_DESKTOP_EXISTING_RESULT " dataUsingEncoding:NSUTF8StringEncoding]];
    [line appendData:json];
    [line appendData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
    return [line writeToFile:path
                     options:(NSDataWritingAtomic | NSDataWritingWithoutOverwriting)
                       error:&error];
}

static BOOL beforeDeadline(unsigned long long expiry, double monotonicEnd) {
    time_t now = time(NULL);
    return !stopSignal && now >= 0 && (unsigned long long)now < expiry &&
           monotonicNow() < monotonicEnd;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 12) return 2;
        NSString *mode = [NSString stringWithUTF8String:argv[1]];
        NSString *nonce = [NSString stringWithUTF8String:argv[2]];
        NSString *outputPath = [NSString stringWithUTF8String:argv[6]];
        NSString *sourceSHA = [NSString stringWithUTF8String:argv[7]];
        NSString *binarySHA = [NSString stringWithUTF8String:argv[8]];
        unsigned long long expiry = 0, hold = 0, registry = 0;
        unsigned long long expectedWidth = 0, expectedHeight = 0;
        double expectedRefresh = 0;
        if (![mode isEqualToString:@"existing-display-production"] ||
            !validHex(nonce, 32) || !validHex(sourceSHA, 64) ||
            !validHex(binarySHA, 64) || outputPath.length == 0 ||
            !parseUnsigned(argv[3], &expiry) || expiry > (unsigned long long)LLONG_MAX ||
            !parseUnsigned(argv[4], &hold) || hold < 1 || hold > 30 ||
            !parseUnsigned(argv[5], &registry) || registry == 0 ||
            !parseUnsigned(argv[9], &expectedWidth) || expectedWidth == 0 ||
            !parseUnsigned(argv[10], &expectedHeight) || expectedHeight == 0 ||
            !parsePositiveDouble(argv[11], &expectedRefresh)) return 2;

        signal(SIGHUP, requestStop);
        signal(SIGINT, requestStop);
        signal(SIGTERM, requestStop);
        signal(SIGALRM, requestStop);
        alarm((unsigned int)hold + 8);

        time_t started = time(NULL);
        NSDictionary *aqua = aquaFacts();
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
        [NSApp finishLaunching];
        pumpRunLoop(0.05);

        CGError displayError = kCGErrorSuccess;
        NSArray<NSNumber *> *onlineIDs = onlineDisplayIDs(&displayError) ?: @[];
        NSArray<NSNumber *> *screenIDs = screenDisplayIDs();
        NSArray<NSScreen *> *screens = NSScreen.screens;
        NSScreen *mainScreen = NSScreen.mainScreen;
        CGDirectDisplayID displayID = onlineIDs.count == 1 ? onlineIDs.firstObject.unsignedIntValue : 0;
        CGDirectDisplayID mainDisplayID = CGMainDisplayID();
        NSNumber *mainScreenNumber = mainScreen.deviceDescription[@"NSScreenNumber"];
        BOOL singleMainScreen = (displayError == kCGErrorSuccess && onlineIDs.count == 1 &&
            screens.count == 1 && screenIDs.count == 1 && displayID != 0 &&
            mainDisplayID == displayID && mainScreenNumber.unsignedIntValue == displayID &&
            [screenIDs isEqualToArray:onlineIDs]);
        BOOL active = displayID != 0 && CGDisplayIsActive(displayID);
        BOOL online = displayID != 0 && CGDisplayIsOnline(displayID);
        size_t width = 0, height = 0;
        double refresh = 0;
        CGDisplayModeRef displayMode = displayID ? CGDisplayCopyDisplayMode(displayID) : NULL;
        if (displayMode) {
            width = CGDisplayModeGetWidth(displayMode);
            height = CGDisplayModeGetHeight(displayMode);
            refresh = CGDisplayModeGetRefreshRate(displayMode);
            CFRelease(displayMode);
        }
        NSRect screenFrame = mainScreen ? mainScreen.frame : NSZeroRect;
        BOOL geometryMatches = (width == expectedWidth && height == expectedHeight &&
            fabs(refresh - expectedRefresh) <= 0.01 &&
            fabs(screenFrame.size.width - (double)expectedWidth) <= 0.01 &&
            fabs(screenFrame.size.height - (double)expectedHeight) <= 0.01);
        BOOL admitted = (started > 0 && (unsigned long long)started <= expiry &&
            expiry - (unsigned long long)started >= hold + 7 &&
            [aqua[@"ready"] boolValue] && singleMainScreen && active && online &&
            geometryMatches);

        id<MTLDevice> device = admitted ? exactDevice(registry) : nil;
        NSString *deviceName = device.name ?: @"";
        id<MTLCommandQueue> queue = device ? [device newCommandQueue] : nil;
        NSWindow *window = nil;
        CAMetalLayer *metalLayer = nil;
        CGDirectDisplayID windowDisplayID = 0;
        BOOL windowVisible = NO;
        NSUInteger acquired = 0, submitted = 0, completionCallbacks = 0;
        NSUInteger completed = 0, presentationCallbacks = 0, presented = 0;
        NSUInteger firstFrame = 0, lastFrame = 0;
        BOOL usedRed = NO, usedCyan = NO;
        NSString *firstColor = @"", *lastColor = @"";

        if (admitted && device && queue && [deviceName isEqualToString:@"AMD Radeon Navi23"]) {
            window = [[NSWindow alloc] initWithContentRect:screenFrame
                styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO
                screen:mainScreen];
            window.opaque = YES;
            window.backgroundColor = NSColor.blackColor;
            window.level = NSScreenSaverWindowLevel;
            window.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces |
                                        NSWindowCollectionBehaviorFullScreenAuxiliary;
            NSView *view = [[NSView alloc] initWithFrame:NSMakeRect(
                0, 0, screenFrame.size.width, screenFrame.size.height)];
            view.wantsLayer = YES;
            metalLayer = [CAMetalLayer layer];
            metalLayer.device = device;
            metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
            metalLayer.framebufferOnly = YES;
            metalLayer.allowsNextDrawableTimeout = YES;
            metalLayer.drawableSize = CGSizeMake(expectedWidth, expectedHeight);
            metalLayer.frame = view.bounds;
            view.layer = metalLayer;
            window.contentView = view;
            [window orderFrontRegardless];
            [NSApp activateIgnoringOtherApps:YES];
            pumpRunLoop(0.05);
            NSNumber *windowNumber = window.screen.deviceDescription[@"NSScreenNumber"];
            windowDisplayID = windowNumber.unsignedIntValue;
            windowVisible = window.visible && windowDisplayID == displayID;
        }

        double holdStart = monotonicNow();
        double holdEnd = holdStart + (double)hold;
        if (windowVisible) {
            for (NSUInteger frameIndex = 0; beforeDeadline(expiry, holdEnd); ++frameIndex) {
                @autoreleasepool {
                    double elapsed = monotonicNow() - holdStart;
                    id<CAMetalDrawable> drawable = [metalLayer nextDrawable];
                    if (!drawable || !beforeDeadline(expiry, holdEnd)) break;
                    acquired++;
                    BOOL cyan = elapsed >= (double)hold / 2.0;
                    NSString *token = cyan ? @"#00ffff" : @"#ff0000";
                    MTLRenderPassDescriptor *pass = MTLRenderPassDescriptor.renderPassDescriptor;
                    pass.colorAttachments[0].texture = drawable.texture;
                    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
                    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
                    pass.colorAttachments[0].clearColor = cyan ?
                        MTLClearColorMake(0, 1, 1, 1) : MTLClearColorMake(1, 0, 0, 1);
                    id<MTLCommandBuffer> command = [queue commandBuffer];
                    id<MTLRenderCommandEncoder> encoder =
                        [command renderCommandEncoderWithDescriptor:pass];
                    if (!command || !encoder) break;
                    [encoder endEncoding];
                    dispatch_semaphore_t completion = dispatch_semaphore_create(0);
                    dispatch_semaphore_t presentation = dispatch_semaphore_create(0);
                    __block CFTimeInterval callbackPresentedTime = 0;
                    [command addCompletedHandler:^(id<MTLCommandBuffer> value) {
                        (void)value;
                        dispatch_semaphore_signal(completion);
                    }];
                    [drawable addPresentedHandler:^(id<MTLDrawable> value) {
                        callbackPresentedTime = value.presentedTime;
                        dispatch_semaphore_signal(presentation);
                    }];
                    [command presentDrawable:drawable];
                    if (!beforeDeadline(expiry, holdEnd)) break;
                    [command commit];
                    submitted++;

                    double completionEnd = fmin(monotonicNow() + 1.0, holdEnd);
                    BOOL completionAck = NO;
                    while (beforeDeadline(expiry, completionEnd)) {
                        if (dispatch_semaphore_wait(completion, DISPATCH_TIME_NOW) == 0) {
                            completionAck = YES;
                            break;
                        }
                        pumpRunLoop(0.01);
                    }
                    if (completionAck) completionCallbacks++;
                    BOOL completedOK = completionAck &&
                        command.status == MTLCommandBufferStatusCompleted;
                    if (completedOK) completed++;

                    double presentationEnd = fmin(monotonicNow() + 1.0, holdEnd);
                    BOOL presentationAck = NO;
                    while (completedOK && beforeDeadline(expiry, presentationEnd)) {
                        if (dispatch_semaphore_wait(presentation, DISPATCH_TIME_NOW) == 0) {
                            presentationAck = YES;
                            break;
                        }
                        pumpRunLoop(0.01);
                    }
                    if (presentationAck) presentationCallbacks++;
                    CFTimeInterval presentedTime = presentationAck ? callbackPresentedTime : 0;
                    if (completedOK && presentationAck && presentedTime > 0) {
                        if (presented == 0) {
                            firstFrame = frameIndex;
                            firstColor = token;
                        }
                        lastFrame = frameIndex;
                        lastColor = token;
                        presented++;
                        if (cyan) usedCyan = YES; else usedRed = YES;
                    } else {
                        break;
                    }
                }
                pumpRunLoop(0.05);
            }
        }

        [window orderOut:nil];
        pumpRunLoop(0.02);
        metalLayer = nil;
        window = nil;
        time_t finished = time(NULL);
        NSDictionary *display = @{
            @"online_ids": onlineIDs, @"nsscreen_ids": screenIDs,
            @"screen_count": @(screens.count), @"display_id": @(displayID),
            @"main_display_id": @(mainDisplayID), @"main": @((BOOL)singleMainScreen),
            @"active": @((BOOL)active), @"online": @((BOOL)online),
            @"width": @(width), @"height": @(height), @"refresh": @(refresh),
            @"expected_width": @(expectedWidth), @"expected_height": @(expectedHeight),
            @"expected_refresh": @(expectedRefresh),
            @"screen_frame_x": @(screenFrame.origin.x),
            @"screen_frame_y": @(screenFrame.origin.y),
            @"screen_frame_width": @(screenFrame.size.width),
            @"screen_frame_height": @(screenFrame.size.height),
            @"ownership": @"preexisting", @"created_by_probe": @NO,
            @"removed_by_probe": @NO,
        };
        NSDictionary *render = @{
            @"registry_id": @(registry), @"device_name": deviceName,
            @"window_display_id": @(windowDisplayID),
            @"window_visible": @((BOOL)windowVisible),
            @"drawables_acquired": @(acquired),
            @"command_buffers_submitted": @(submitted),
            @"completion_callbacks_observed": @(completionCallbacks),
            @"command_buffers_completed": @(completed),
            @"presentation_callbacks_observed": @(presentationCallbacks),
            @"presented_frames": @(presented), @"first_frame": @(firstFrame),
            @"last_frame": @(lastFrame),
            @"distinct_color_tokens": @((usedRed ? 1 : 0) + (usedCyan ? 1 : 0)),
            @"first_color_token": firstColor, @"last_color_token": lastColor,
        };
        NSDictionary *receipt = @{
            @"schema": @1, @"nonce": nonce, @"execution_mode": mode,
            @"source_sha256": sourceSHA, @"binary_sha256": binarySHA,
            @"guest_binary": [NSString stringWithUTF8String:argv[0]],
            @"expiry_epoch": @(expiry), @"started_epoch": @(started),
            @"finished_epoch": @(finished), @"hold_seconds": @(hold),
            @"aqua": aqua, @"display": display, @"render": render,
            @"provenance": @{
                @"existing_display_origin": @"qemu-generic-graphics",
                @"existing_display_origin_basis": @"pinned_launch_profile",
                @"render_device_origin": @"exact_raphael_registry",
                @"render_device_observed": @((BOOL)(device != nil)),
                @"compositor_gpu_provenance": @"unproven",
                @"scanout_gpu_provenance": @"unproven",
            },
            @"remote_observation": @{
                @"required": @YES, @"observed": @NO,
                @"frame_change_observed": @NO,
                @"evidence": @"external_capture_required",
            },
        };
        alarm(0);
        BOOL wrote = writeReceipt(receipt, outputPath);
        BOOL countsExact = (acquired >= 2 && acquired == submitted &&
            submitted == completionCallbacks && completionCallbacks == completed &&
            completed == presentationCallbacks && presentationCallbacks == presented);
        BOOL stimulusSuccess = countsExact && usedRed && usedCyan && lastFrame > firstFrame &&
            [firstColor isEqualToString:@"#ff0000"] &&
            [lastColor isEqualToString:@"#00ffff"];
        BOOL success = ([aqua[@"ready"] boolValue] && singleMainScreen && active && online &&
            geometryMatches && device && queue &&
            [deviceName isEqualToString:@"AMD Radeon Navi23"] && windowVisible &&
            stimulusSuccess && finished > 0 && (unsigned long long)finished <= expiry);
        if (stopSignal == SIGALRM) return 124;
        return wrote && success ? 0 : 1;
    }
}
