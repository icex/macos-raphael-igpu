// List or set the guest's main display mode (logical size, HiDPI, refresh), no permissions.
//
//   rgpu-display-mode                      list modes (current marked *)
//   rgpu-display-mode WIDTH HEIGHT HZ      set the HiDPI mode with that logical size and refresh
//
// Build: xcrun clang -fobjc-arc -O2 -framework CoreGraphics -framework Foundation
//        rgpu-display-mode.m -o rgpu-display-mode
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        CGDirectDisplayID display = CGMainDisplayID();
        NSDictionary *options = @{(__bridge NSString *)kCGDisplayShowDuplicateLowResolutionModes: @YES};
        NSArray *modes = CFBridgingRelease(CGDisplayCopyAllDisplayModes(display, (__bridge CFDictionaryRef)options));
        CGDisplayModeRef current = CGDisplayCopyDisplayMode(display);
        if (argc < 4) {
            for (id m in modes) {
                CGDisplayModeRef mode = (__bridge CGDisplayModeRef)m;
                printf("%c %zux%zu (%zux%zu px) %.0f Hz\n", CGDisplayModeGetIODisplayModeID(mode) ==
                       CGDisplayModeGetIODisplayModeID(current) ? '*' : ' ',
                       CGDisplayModeGetWidth(mode), CGDisplayModeGetHeight(mode),
                       CGDisplayModeGetPixelWidth(mode), CGDisplayModeGetPixelHeight(mode),
                       CGDisplayModeGetRefreshRate(mode));
            }
            CGDisplayModeRelease(current);
            return 0;
        }
        size_t width = (size_t)atol(argv[1]), height = (size_t)atol(argv[2]);
        double hz = atof(argv[3]);
        for (id m in modes) {
            CGDisplayModeRef mode = (__bridge CGDisplayModeRef)m;
            if (CGDisplayModeGetWidth(mode) == width && CGDisplayModeGetHeight(mode) == height &&
                CGDisplayModeGetPixelWidth(mode) == 2 * width && fabs(CGDisplayModeGetRefreshRate(mode) - hz) < 0.5) {
                CGError error = CGDisplaySetDisplayMode(display, mode, NULL);
                printf("set %zux%zu HiDPI %.0f Hz: %d\n", width, height, hz, error);
                CGDisplayModeRelease(current);
                return error == kCGErrorSuccess ? 0 : 1;
            }
        }
        fprintf(stderr, "no HiDPI %zux%zu mode at %.0f Hz\n", width, height, hz);
        CGDisplayModeRelease(current);
        return 1;
    }
}
