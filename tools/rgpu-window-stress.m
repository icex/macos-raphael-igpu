// Window-drag stress for the guest desktop: large windows with changing content move
// continuously along smooth paths and are resized every two seconds, so WindowServer keeps
// compositing and allocating new window surfaces, the way a user dragging and resizing does.
// The app records how evenly its 120 Hz move timer runs (main-thread hitches) and prints one
// JSON line. No Accessibility or Screen Recording permission is needed: it moves its own
// windows.
//
//   rgpu-window-stress SECONDS OUTPUT.json [WINDOWS]
//
// Build: xcrun clang -fobjc-arc -O2 -framework AppKit -framework QuartzCore
//        rgpu-window-stress.m -o rgpu-window-stress   (run it inside an .app via `open`)
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>
#import <Metal/Metal.h>
#include <math.h>

@interface StressView : NSView
@property double phase;
@end
@implementation StressView
- (void)drawRect:(NSRect)dirty {
    (void)dirty;
    NSRect b = self.bounds;
    double p = self.phase;
    NSColor *a = [NSColor colorWithCalibratedHue:fmod(p * 0.05, 1.0) saturation:0.7 brightness:0.9 alpha:1];
    NSColor *c = [NSColor colorWithCalibratedHue:fmod(p * 0.05 + 0.5, 1.0) saturation:0.7 brightness:0.6 alpha:1];
    [[[NSGradient alloc] initWithStartingColor:a endingColor:c] drawInRect:b angle:fmod(p * 20, 360)];
    NSString *text = [NSString stringWithFormat:@"rgpu window stress %.2f", p];
    [text drawAtPoint:NSMakePoint(40, b.size.height / 2)
       withAttributes:@{NSFontAttributeName: [NSFont boldSystemFontOfSize:48],
                        NSForegroundColorAttributeName: NSColor.whiteColor}];
}
@end

static NSMutableArray<NSNumber *> *presented;
@interface PresentView : NSView
@property id<MTLDevice> device;
@property id<MTLCommandQueue> queue;
@end
@implementation PresentView
- (CALayer *)makeBackingLayer {
    CAMetalLayer *layer = [CAMetalLayer layer];
    self.device = MTLCreateSystemDefaultDevice();
    self.queue = [self.device newCommandQueue];
    layer.device = self.device;
    layer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    return layer;
}
- (void)renderPhase:(double)p {
    CAMetalLayer *layer = (CAMetalLayer *)self.layer;
    layer.drawableSize = NSMakeSize(self.bounds.size.width * 2, self.bounds.size.height * 2);
    id<CAMetalDrawable> drawable = [layer nextDrawable];
    if (!drawable) return;
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = drawable.texture;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0.5 + 0.5 * sin(p), 0.3, 0.5 + 0.5 * cos(p), 1);
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLCommandBuffer> command = [self.queue commandBuffer];
    [[command renderCommandEncoderWithDescriptor:pass] endEncoding];
    [drawable addPresentedHandler:^(id<MTLDrawable> d) {
        if (d.presentedTime > 0) @synchronized (presented) { [presented addObject:@(d.presentedTime)]; }
    }];
    [command presentDrawable:drawable];
    [command commit];
}
@end

@interface Stress : NSObject <NSApplicationDelegate>
@property NSMutableArray<NSWindow *> *windows;
@property double start, last, seconds, nextResize;
@property NSUInteger ticks, hitches50, hitches100, resizes;
@property double worstGap;
@property NSString *output;
@property NSUInteger count;
@property NSWindow *probe;
@end

@implementation Stress
- (void)applicationDidFinishLaunching:(NSNotification *)note {
    (void)note;
    NSRect screen = NSScreen.mainScreen.visibleFrame;
    self.windows = [NSMutableArray array];
    for (NSUInteger i = 0; i < self.count; i++) {
        NSRect frame = NSMakeRect(screen.origin.x + 100 + 80 * i, screen.origin.y + 100 + 60 * i,
                                  screen.size.width * 0.45, screen.size.height * 0.45);
        NSWindow *w = [[NSWindow alloc] initWithContentRect:frame
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskResizable
              backing:NSBackingStoreBuffered defer:NO];
        w.title = [NSString stringWithFormat:@"rgpu stress %lu", (unsigned long)i];
        w.contentView = [[StressView alloc] initWithFrame:frame];
        w.releasedWhenClosed = NO;
        [w makeKeyAndOrderFront:nil];
        [self.windows addObject:w];
    }
    presented = [NSMutableArray array];
    self.probe = [[NSWindow alloc] initWithContentRect:NSMakeRect(screen.origin.x + 40, screen.origin.y + 40, 480, 270)
        styleMask:NSWindowStyleMaskTitled backing:NSBackingStoreBuffered defer:NO];
    self.probe.title = @"rgpu present probe";
    PresentView *pv = [[PresentView alloc] initWithFrame:NSMakeRect(0, 0, 480, 270)];
    pv.wantsLayer = YES;
    self.probe.contentView = pv;
    self.probe.releasedWhenClosed = NO;
    [self.probe makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    self.start = self.last = CACurrentMediaTime();
    self.nextResize = self.start + 2;
    NSTimer *timer = [NSTimer timerWithTimeInterval:1.0 / 120 target:self selector:@selector(tick:)
                                          userInfo:nil repeats:YES];
    [NSRunLoop.mainRunLoop addTimer:timer forMode:NSRunLoopCommonModes];
}
- (void)tick:(NSTimer *)timer {
    double now = CACurrentMediaTime(), gap = now - self.last;
    self.last = now;
    self.ticks++;
    if (gap > 0.050) self.hitches50++;
    if (gap > 0.100) self.hitches100++;
    if (gap > self.worstGap) self.worstGap = gap;
    double t = now - self.start;
    NSRect screen = NSScreen.mainScreen.visibleFrame;
    BOOL resize = now >= self.nextResize;
    if (resize) { self.nextResize = now + 2; self.resizes++; }
    for (NSUInteger i = 0; i < self.windows.count; i++) {
        NSWindow *w = self.windows[i];
        NSSize size = w.frame.size;
        if (resize) {
            double f = 0.30 + 0.25 * fabs(sin(t * 0.7 + i));
            size = NSMakeSize(screen.size.width * f, screen.size.height * (0.30 + 0.25 * fabs(cos(t * 0.5 + i))));
        }
        double rx = (screen.size.width - size.width) / 2, ry = (screen.size.height - size.height) / 2;
        NSPoint origin = NSMakePoint(screen.origin.x + rx + rx * sin(t * (1.1 + 0.3 * i)),
                                     screen.origin.y + ry + ry * sin(t * (1.7 + 0.2 * i) + i));
        [w setFrame:NSMakeRect(origin.x, origin.y, size.width, size.height) display:YES];
        StressView *v = (StressView *)w.contentView;
        v.phase = t + i;
        v.needsDisplay = YES;
    }
    PresentView *pv = (PresentView *)self.probe.contentView;
    NSRect pf = self.probe.frame;
    [self.probe setFrameOrigin:NSMakePoint(screen.origin.x + (screen.size.width - pf.size.width) * (0.5 + 0.5 * sin(t * 1.3)),
                                           screen.origin.y + (screen.size.height - pf.size.height) * (0.5 + 0.5 * cos(t * 0.9)))];
    [pv renderPhase:t];
    if (t >= self.seconds) {
        [timer invalidate];
        NSArray<NSNumber *> *times;
        @synchronized (presented) { times = [presented copy]; }
        NSMutableArray<NSNumber *> *gaps = [NSMutableArray array];
        for (NSUInteger k = 1; k < times.count; k++)
            [gaps addObject:@((times[k].doubleValue - times[k - 1].doubleValue) * 1000)];
        NSArray<NSNumber *> *sorted = [gaps sortedArrayUsingSelector:@selector(compare:)];
        double span = times.count > 1 ? times.lastObject.doubleValue - times.firstObject.doubleValue : 0;
        NSUInteger over25 = 0, over50 = 0, over100 = 0;
        for (NSNumber *g in gaps) { over25 += g.doubleValue > 25; over50 += g.doubleValue > 50; over100 += g.doubleValue > 100; }
        NSDictionary *present = sorted.count ? @{@"frames": @(times.count), @"fps": @(span > 0 ? (times.count - 1) / span : 0),
            @"p50_ms": sorted[sorted.count / 2], @"p95_ms": sorted[sorted.count * 95 / 100],
            @"p99_ms": sorted[sorted.count * 99 / 100], @"max_ms": sorted.lastObject,
            @"gaps_over_25ms": @(over25), @"gaps_over_50ms": @(over50), @"gaps_over_100ms": @(over100)} : @{@"frames": @0};
        NSDictionary *result = @{@"present": present,@"seconds": @(t), @"windows": @(self.windows.count),
            @"ticks": @(self.ticks), @"ticks_per_second": @(self.ticks / t),
            @"hitches_over_50ms": @(self.hitches50), @"hitches_over_100ms": @(self.hitches100),
            @"worst_gap_ms": @(self.worstGap * 1000), @"resizes": @(self.resizes)};
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        [json writeToFile:self.output atomically:YES];
        [NSApp terminate:nil];
    }
}
@end

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 3) { fprintf(stderr, "usage: %s SECONDS OUTPUT.json [WINDOWS]\n", argv[0]); return 2; }
        NSApplication *app = NSApplication.sharedApplication;
        (void)0;
        app.activationPolicy = NSApplicationActivationPolicyRegular;
        Stress *stress = [Stress new];
        stress.seconds = atof(argv[1]);
        stress.output = [NSString stringWithUTF8String:argv[2]];
        stress.count = argc > 3 ? (NSUInteger)atoi(argv[3]) : 3;
        app.delegate = stress;
        [app run];
    }
    return 0;
}
