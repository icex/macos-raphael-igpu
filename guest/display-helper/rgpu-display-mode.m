// Select logical WxH at scale (1 or 2) and refresh on the display with vendor/product.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 7) return 2;
    uint32_t vendor = atoi(argv[1]), product = atoi(argv[2]);
    size_t w = atoi(argv[3]), h = atoi(argv[4]), scale = atoi(argv[5]); double hz = atof(argv[6]);
    CGDirectDisplayID ids[16]; uint32_t n = 0, target = 0;
    if (CGGetOnlineDisplayList(16, ids, &n)) return 3;
    for (uint32_t i = 0; i < n; i++)
        if (CGDisplayVendorNumber(ids[i]) == vendor && CGDisplayModelNumber(ids[i]) == product) target = ids[i];
    if (!target) return 4;
    CFArrayRef modes = CGDisplayCopyAllDisplayModes(target,
        (__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes: @YES});
    CGDisplayModeRef best = NULL;
    for (CFIndex i = 0; modes && i < CFArrayGetCount(modes); i++) {
        CGDisplayModeRef m = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes, i);
        if (CGDisplayModeGetWidth(m) != w || CGDisplayModeGetHeight(m) != h ||
            CGDisplayModeGetPixelWidth(m) != w * scale || CGDisplayModeGetPixelHeight(m) != h * scale) continue;
        if (!best || fabs(CGDisplayModeGetRefreshRate(m) - hz) < fabs(CGDisplayModeGetRefreshRate(best) - hz)) best = m;
    }
    if (!best) { if (modes) CFRelease(modes); return 5; }
    CGDisplayConfigRef config = NULL;
    CGError e = CGBeginDisplayConfiguration(&config);
    if (!e) e = CGConfigureDisplayWithDisplayMode(config, target, best, NULL);
    if (!e) e = CGCompleteDisplayConfiguration(config, kCGConfigurePermanently);
    else if (config) CGCancelDisplayConfiguration(config);
    printf("selected %zux%zu@%zux %.2fHz err=%d\n", w, h, scale, CGDisplayModeGetRefreshRate(best), e);
    CFRelease(modes);
    return e ? 6 : 0; } }
