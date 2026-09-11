#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <SystemConfiguration/SystemConfiguration.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <libproc.h>
#include <signal.h>
#include <sys/sysctl.h>
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

static void deadline(int signalNumber) {
    (void)signalNumber;
    _exit(124);
}

static BOOL processNamed(const char *wanted) {
    int count = proc_listallpids(NULL, 0);
    if (count <= 0) return NO;
    pid_t *pids = calloc((size_t)count, sizeof(pid_t));
    if (!pids) return NO;
    count = proc_listallpids(pids, count * (int)sizeof(pid_t));
    BOOL found = NO;
    for (int index = 0; index < count && !found; ++index) {
        char name[PROC_PIDPATHINFO_MAXSIZE] = {};
        if (pids[index] > 0 && proc_name(pids[index], name, sizeof(name)) > 0)
            found = strcmp(name, wanted) == 0;
    }
    free(pids);
    return found;
}

static BOOL validNonce(NSString *nonce) {
    if (nonce.length != 32) return NO;
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:
        @"0123456789abcdef"] invertedSet];
    return [nonce rangeOfCharacterFromSet:invalid].location == NSNotFound;
}

static NSArray *onlineDisplayIDs(CGError *errorOut) {
    CGDirectDisplayID ids[32] = {};
    uint32_t count = 0;
    CGError error = CGGetOnlineDisplayList(32, ids, &count);
    if (errorOut) *errorOut = error;
    if (error != kCGErrorSuccess) return nil;
    NSMutableArray *result = [NSMutableArray arrayWithCapacity:count];
    for (uint32_t index = 0; index < count; ++index) [result addObject:@(ids[index])];
    return result;
}

static BOOL argumentMatches(Class owner, NSString *name, NSUInteger index,
                            const char *expected) {
    NSMethodSignature *signature = [owner instanceMethodSignatureForSelector:
        NSSelectorFromString(name)];
    return signature && index < signature.numberOfArguments &&
        strcmp([signature getArgumentTypeAtIndex:index], expected) == 0;
}

static BOOL stage2ABIValid(void) {
    Class descriptor = NSClassFromString(@"CGVirtualDisplayDescriptor");
    Class mode = NSClassFromString(@"CGVirtualDisplayMode");
    Class settings = NSClassFromString(@"CGVirtualDisplaySettings");
    for (NSString *setter in @[@"setVendorID:", @"setProductID:", @"setSerialNum:",
            @"setSerialNumber:", @"setMaxPixelsWide:", @"setMaxPixelsHigh:"])
        if (!argumentMatches(descriptor, setter, 2, @encode(unsigned int))) return NO;
    if (!argumentMatches(mode, @"initWithWidth:height:refreshRate:", 2,
                         @encode(unsigned int)) ||
        !argumentMatches(mode, @"initWithWidth:height:refreshRate:", 3,
                         @encode(unsigned int)) ||
        !argumentMatches(mode, @"initWithWidth:height:refreshRate:", 4,
                         @encode(double)) ||
        !argumentMatches(settings, @"setHiDPI:", 2, @encode(unsigned int)) ||
        !argumentMatches(settings, @"setRotation:", 2, @encode(unsigned int))) return NO;
    return YES;
}

static NSDictionary *methodEncodings(void) {
    NSDictionary *owners = @{
        @"display_init": @[@"CGVirtualDisplay", @"initWithDescriptor:"],
        @"mode_init": @[@"CGVirtualDisplayMode", @"initWithWidth:height:refreshRate:"],
        @"serial_num": @[@"CGVirtualDisplayDescriptor", @"setSerialNum:"],
        @"serial_number": @[@"CGVirtualDisplayDescriptor", @"setSerialNumber:"],
        @"hi_dpi": @[@"CGVirtualDisplaySettings", @"setHiDPI:"],
        @"rotation": @[@"CGVirtualDisplaySettings", @"setRotation:"],
    };
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSString *key in owners) {
        NSArray *pair = owners[key];
        Method method = class_getInstanceMethod(NSClassFromString(pair[0]),
                                                 NSSelectorFromString(pair[1]));
        const char *encoding = method ? method_getTypeEncoding(method) : NULL;
        result[key] = encoding ? [NSString stringWithUTF8String:encoding] : @"";
    }
    return result;
}

static NSDictionary *sessionFacts(void) {
    NSDictionary *session = CFBridgingRelease(CGSessionCopyCurrentDictionary());
    NSDictionary *keys = @{
        @"user_id": (__bridge NSString *)kCGSessionUserIDKey,
        @"user_name": (__bridge NSString *)kCGSessionUserNameKey,
        @"login_done": (__bridge NSString *)kCGSessionLoginDoneKey,
        @"on_console": (__bridge NSString *)kCGSessionOnConsoleKey,
        @"console_set": (__bridge NSString *)kCGSessionConsoleSetKey,
    };
    NSMutableDictionary *result = [NSMutableDictionary dictionary];
    for (NSString *outputKey in keys) {
        id value = session[keys[outputKey]];
        result[outputKey] = ([value isKindOfClass:[NSString class]] ||
                             [value isKindOfClass:[NSNumber class]]) ? value : [NSNull null];
    }
    return result;
}

static NSDictionary *createRemove(NSString *nonce) {
    CGError baselineError = kCGErrorSuccess;
    NSArray *baseline = onlineDisplayIDs(&baselineError);
    BOOL created = NO, applied = NO, added = NO, active = NO, removed = NO;
    BOOL abiValid = stage2ABIValid();
    BOOL terminated = NO;
    CGDirectDisplayID displayID = 0;
    size_t width = 0, height = 0;
    double refresh = 0;
    NSArray *finalIDs = baseline ?: @[];
    CGVirtualDisplay *display = nil;
    if (abiValid && baselineError == kCGErrorSuccess && baseline.count == 0) {
        unsigned int serial = 0;
        [[NSScanner scannerWithString:[nonce substringToIndex:8]] scanHexInt:&serial];
        if (serial == 0) serial = 1;
        CGVirtualDisplayDescriptor *descriptor = [CGVirtualDisplayDescriptor new];
        // Match Chromium's binary-derived descriptor sequence and constants.
        descriptor.queue = dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_HIGH, 0);
        descriptor.name = @"Raphael disposable display";
        descriptor.whitePoint = CGPointMake(0.3125, 0.3291);
        descriptor.bluePrimary = CGPointMake(0.1494, 0.0557);
        descriptor.greenPrimary = CGPointMake(0.2559, 0.6983);
        descriptor.redPrimary = CGPointMake(0.6797, 0.3203);
        descriptor.maxPixelsHigh = 720; descriptor.maxPixelsWide = 1280;
        descriptor.sizeInMillimeters = CGSizeMake(25.4 * 1280 / 100,
                                                  25.4 * 720 / 100);
        descriptor.serialNum = serial; descriptor.productID = 0;
        descriptor.vendorID = 505; descriptor.terminationHandler = nil;
        descriptor.serialNumber = serial;
        display = [[CGVirtualDisplay alloc] initWithDescriptor:descriptor];
        created = display != nil;
        if (display) {
            displayID = display.displayID;
            CGVirtualDisplayMode *mode = [[CGVirtualDisplayMode alloc]
                initWithWidth:1280 height:720 refreshRate:60.0];
            CGVirtualDisplaySettings *settings = [CGVirtualDisplaySettings new];
            if (mode) {
                settings.modes = @[mode]; settings.hiDPI = 0; settings.rotation = 0;
                applied = [display applySettings:settings];
            }
            for (int attempt = 0; attempt < 40 &&
                    !(added && active && width == 1280 && height == 720 && refresh == 60.0);
                    ++attempt) {
                NSArray *current = onlineDisplayIDs(NULL);
                added = [current containsObject:@(displayID)];
                active = added && CGDisplayIsActive(displayID) != 0;
                CGDisplayModeRef currentMode = added ? CGDisplayCopyDisplayMode(displayID) : NULL;
                if (currentMode) {
                    width = CGDisplayModeGetWidth(currentMode);
                    height = CGDisplayModeGetHeight(currentMode);
                    refresh = CGDisplayModeGetRefreshRate(currentMode);
                    CFRelease(currentMode);
                }
                if (!(added && active && width == 1280 && height == 720 && refresh == 60.0))
                    usleep(100000);
            }
            usleep(1000000);
            display = nil;
            for (int attempt = 0; attempt < 40 && !removed; ++attempt) {
                finalIDs = onlineDisplayIDs(NULL);
                removed = finalIDs && ![finalIDs containsObject:@(displayID)];
                if (!removed) usleep(100000);
            }
        }
    }
    BOOL cleanup = baseline && finalIDs && [finalIDs isEqualToArray:baseline];
    return @{ @"schema": @1, @"nonce": nonce, @"abi_valid": @((BOOL)abiValid),
              @"session": sessionFacts(), @"method_encodings": methodEncodings(),
              @"baseline_ids": baseline ?: @[],
              @"created": @((BOOL)created), @"display_id": @(displayID),
              @"settings_applied": @((BOOL)applied), @"added": @((BOOL)added),
              @"active": @((BOOL)active), @"width": @(width), @"height": @(height),
              @"refresh": @(refresh), @"retained_milliseconds": @1000,
              @"removed": @((BOOL)removed), @"termination_called": @((BOOL)terminated),
              @"final_ids": finalIDs ?: @[], @"cleanup_complete": @((BOOL)cleanup) };
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3) return 2;
        signal(SIGALRM, deadline);
        alarm(15);
        NSString *nonce = [NSString stringWithUTF8String:argv[1]];
        if (!validNonce(nonce)) return 2;
        NSString *action = [NSString stringWithUTF8String:argv[2]];
        if ([action isEqualToString:@"create-remove"]) {
            NSDictionary *result = createRemove(nonce);
            NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            alarm(0);
            printf("RGPU_VDISPLAY_CREATE %.*s\n", (int)json.length,
                   (const char *)json.bytes);
            fflush(stdout);
            return 0;
        }
        if (![action isEqualToString:@"inventory"]) return 2;

        NSArray *classNames = @[@"CGVirtualDisplay", @"CGVirtualDisplayDescriptor",
                                @"CGVirtualDisplayMode", @"CGVirtualDisplaySettings"];
        NSMutableDictionary *classes = [NSMutableDictionary dictionary];
        for (NSString *name in classNames)
            classes[name] = @((BOOL)(NSClassFromString(name) != Nil));

        NSDictionary *selectorOwners = @{
            @"initWithDescriptor_": @[@"CGVirtualDisplay", @"initWithDescriptor:"],
            @"applySettings_": @[@"CGVirtualDisplay", @"applySettings:"],
            @"displayID": @[@"CGVirtualDisplay", @"displayID"],
            @"initWithWidth_height_refreshRate_": @[@"CGVirtualDisplayMode", @"initWithWidth:height:refreshRate:"],
            @"setDispatchQueue_": @[@"CGVirtualDisplayDescriptor", @"setDispatchQueue:"],
            @"setVendorID_": @[@"CGVirtualDisplayDescriptor", @"setVendorID:"],
            @"setProductID_": @[@"CGVirtualDisplayDescriptor", @"setProductID:"],
            @"setSerialNum_": @[@"CGVirtualDisplayDescriptor", @"setSerialNum:"],
            @"setSerialNumber_": @[@"CGVirtualDisplayDescriptor", @"setSerialNumber:"],
            @"setName_": @[@"CGVirtualDisplayDescriptor", @"setName:"],
            @"setWhitePoint_": @[@"CGVirtualDisplayDescriptor", @"setWhitePoint:"],
            @"setBluePrimary_": @[@"CGVirtualDisplayDescriptor", @"setBluePrimary:"],
            @"setGreenPrimary_": @[@"CGVirtualDisplayDescriptor", @"setGreenPrimary:"],
            @"setRedPrimary_": @[@"CGVirtualDisplayDescriptor", @"setRedPrimary:"],
            @"setMaxPixelsHigh_": @[@"CGVirtualDisplayDescriptor", @"setMaxPixelsHigh:"],
            @"setMaxPixelsWide_": @[@"CGVirtualDisplayDescriptor", @"setMaxPixelsWide:"],
            @"setSizeInMillimeters_": @[@"CGVirtualDisplayDescriptor", @"setSizeInMillimeters:"],
            @"setTerminationHandler_": @[@"CGVirtualDisplayDescriptor", @"setTerminationHandler:"],
            @"setModes_": @[@"CGVirtualDisplaySettings", @"setModes:"],
            @"setHiDPI_": @[@"CGVirtualDisplaySettings", @"setHiDPI:"],
            @"setRotation_": @[@"CGVirtualDisplaySettings", @"setRotation:"],
        };
        NSMutableDictionary *selectors = [NSMutableDictionary dictionary];
        for (NSString *key in selectorOwners) {
            NSArray *pair = selectorOwners[key];
            Class owner = NSClassFromString(pair[0]);
            selectors[key] = @((BOOL)(owner && class_getInstanceMethod(owner,
                NSSelectorFromString(pair[1])) != NULL));
        }

        CGDirectDisplayID ids[32] = {};
        uint32_t count = 0;
        CGError displayError = CGGetOnlineDisplayList(32, ids, &count);
        NSMutableArray *displays = [NSMutableArray array];
        if (displayError == kCGErrorSuccess) {
            for (uint32_t index = 0; index < count; ++index) {
                CGRect bounds = CGDisplayBounds(ids[index]);
                CGDisplayModeRef mode = CGDisplayCopyDisplayMode(ids[index]);
                [displays addObject:@{
                    @"id": @(ids[index]), @"online": @((BOOL)(CGDisplayIsOnline(ids[index]) != 0)),
                    @"active": @((BOOL)(CGDisplayIsActive(ids[index]) != 0)),
                    @"builtin": @((BOOL)(CGDisplayIsBuiltin(ids[index]) != 0)),
                    @"main": @((BOOL)(CGDisplayIsMain(ids[index]) != 0)),
                    @"vendor": @(CGDisplayVendorNumber(ids[index])),
                    @"model": @(CGDisplayModelNumber(ids[index])),
                    @"serial": @(CGDisplaySerialNumber(ids[index])),
                    @"x": @(bounds.origin.x), @"y": @(bounds.origin.y),
                    @"width": @(mode ? CGDisplayModeGetWidth(mode) : 0),
                    @"height": @(mode ? CGDisplayModeGetHeight(mode) : 0),
                    @"refresh": @(mode ? CGDisplayModeGetRefreshRate(mode) : 0),
                }];
                if (mode) CFRelease(mode);
            }
        }

        uid_t uid = 0; gid_t gid = 0;
        CFStringRef console = SCDynamicStoreCopyConsoleUser(NULL, &uid, &gid);
        NSString *consoleUser = CFBridgingRelease(console) ?: @"";
        char build[256] = {}; size_t buildSize = sizeof(build);
        if (sysctlbyname("kern.osversion", build, &buildSize, NULL, 0) != 0) build[0] = 0;
        void *screenCaptureKit = dlopen(
            "/System/Library/Frameworks/ScreenCaptureKit.framework/ScreenCaptureKit",
            RTLD_LAZY | RTLD_LOCAL);
        Class shareable = NSClassFromString(@"SCShareableContent");
        NSDictionary *result = @{
            @"schema": @1, @"nonce": nonce, @"os_build": @(build),
            @"console_uid": @(uid), @"console_user": consoleUser,
            @"window_server_running": @((BOOL)processNamed("WindowServer")),
            @"screen_capture_preflight": @((BOOL)CGPreflightScreenCaptureAccess()),
            @"classes": classes, @"selectors": selectors,
            @"screen_capture_kit": @{
                @"class": @((BOOL)(shareable != Nil)),
                @"selector": @((BOOL)(shareable && [shareable respondsToSelector:
                    NSSelectorFromString(@"getShareableContentWithCompletionHandler:")])),
            },
            @"online_displays": displays, @"display_list_error": @(displayError),
        };
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        alarm(0);
        printf("RGPU_VDISPLAY_INVENTORY %.*s\n", (int)json.length,
               (const char *)json.bytes);
        fflush(stdout);
        if (screenCaptureKit) dlclose(screenCaptureKit);
        return 0;
    }
}
