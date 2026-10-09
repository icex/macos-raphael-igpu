// Bounded, visible VM-console input qualification. Does not change display mode.
// Drive real manager-window input; raw SPICE/QMP injection bypasses this test's scope.
#import <AppKit/AppKit.h>
#include <signal.h>
#include <unistd.h>
#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

static void expired(int signalNumber) { (void)signalNumber; _exit(124); }
static BOOL saveJSON(NSString *path, NSDictionary *value) {
    NSError *error=nil;
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:&error];
    return data && [data writeToFile:path options:NSDataWritingAtomic error:&error];
}
static NSArray *rectValues(NSRect r) {
    return @[@(r.origin.x),@(r.origin.y),@(r.size.width),@(r.size.height)];
}
// Read the original target again rather than trusting a cached NSScreen. Also
// retain main/window identity: a new screen with identical dimensions is a change.
static NSDictionary *targetSnapshot(CGDirectDisplayID target, NSWindow *window, NSView *view) {
    NSScreen *current=nil;
    for(NSScreen *candidate in NSScreen.screens)
        if([candidate.deviceDescription[@"NSScreenNumber"] unsignedIntValue]==target) { current=candidate;break; }
    CGDisplayModeRef mode=CGDisplayCopyDisplayMode(target);
    NSDictionary *snapshot=@{
        @"target_display":@(target),@"target_present":@(current!=nil),@"online":@(CGDisplayIsOnline(target)),
        @"vendor":@(CGDisplayVendorNumber(target)),@"model":@(CGDisplayModelNumber(target)),
        @"serial":@(CGDisplaySerialNumber(target)),@"mirrors_display":@(CGDisplayMirrorsDisplay(target)),
        @"main_display":NSScreen.mainScreen.deviceDescription[@"NSScreenNumber"] ?: @0,
        @"window_display":window.screen.deviceDescription[@"NSScreenNumber"] ?: @0,
        @"screen_frame":rectValues(current ? current.frame : NSZeroRect),
        @"cg_frame":rectValues(CGDisplayBounds(target)),@"rotation":@(CGDisplayRotation(target)),
        @"window_frame":rectValues(window.frame),@"view_bounds":rectValues(view.bounds),
        @"backing_scale":@(current ? current.backingScaleFactor : 0),
        @"window_backing_scale":@(window.backingScaleFactor),
        @"mode_present":@(mode!=NULL),@"mode_id":@(mode ? CGDisplayModeGetIODisplayModeID(mode) : 0),
        @"refresh_hz":@(mode ? CGDisplayModeGetRefreshRate(mode) : 0),
        @"cg_physical_size":@[@(mode ? CGDisplayModeGetPixelWidth(mode) : 0),@(mode ? CGDisplayModeGetPixelHeight(mode) : 0)],
        @"cg_logical_size":@[@(mode ? CGDisplayModeGetWidth(mode) : 0),@(mode ? CGDisplayModeGetHeight(mode) : 0)]};
    if(mode)CGDisplayModeRelease(mode);
    return snapshot;
}
@interface ViewportWindow : NSWindow
@end
@implementation ViewportWindow
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)canBecomeMainWindow { return YES; }
@end
@interface ViewportView : NSView
@property NSUInteger step;
@property(copy) NSString *token;
@property(strong) NSArray<NSValue *> *targets;
@end
@implementation ViewportView
- (BOOL)isFlipped { return YES; }
- (BOOL)acceptsFirstMouse:(NSEvent *)event { (void)event; return YES; }
- (void)drawRect:(NSRect)dirty {
    (void)dirty;
    [[NSColor colorWithCalibratedWhite:0.16 alpha:1] setFill]; NSRectFill(self.bounds);
    NSDictionary *attributes=@{NSFontAttributeName:[NSFont systemFontOfSize:24],
                               NSForegroundColorAttributeName:NSColor.whiteColor};
    NSString *message=self.step<5 ? [NSString stringWithFormat:@"Click cyan target %lu of 5",(unsigned long)self.step+1]
                                  : [@"Type " stringByAppendingString:self.token];
    [message drawAtPoint:NSMakePoint(100,120) withAttributes:attributes];
    if(self.step<5) {
        NSPoint p=self.targets[self.step].pointValue;
        [[NSColor cyanColor] setFill];NSRectFill(NSMakeRect(p.x-24,p.y-24,48,48));
        [[NSColor blackColor] setFill];NSRectFill(NSMakeRect(p.x-2,p.y-12,4,24));
        NSRectFill(NSMakeRect(p.x-12,p.y-2,24,4));
    }
}
@end
int main(int argc,const char **argv) { @autoreleasepool {
    if(argc!=4 || strlen(argv[2])!=8) return 2;
    for(int n=0;n<8;n++) if(!isxdigit((unsigned char)argv[2][n])) return 2;
    char *end=NULL;long duration=strtol(argv[3],&end,10);
    if(*end || duration<10 || duration>600) return 2;
    NSString *prefix=[NSString stringWithUTF8String:argv[1]];
    if(![prefix hasPrefix:@"/"]) return 2;
    NSString *ready=[prefix stringByAppendingString:@"-ready.json"];
    NSString *result=[prefix stringByAppendingString:@"-result.json"];
    if([NSFileManager.defaultManager fileExistsAtPath:ready] ||
       [NSFileManager.defaultManager fileExistsAtPath:result]) return 2;
    signal(SIGALRM,expired);alarm((unsigned)duration+10);
    [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    NSScreen *screen=NSScreen.mainScreen;if(!screen) return 3;
    NSRect frame=screen.frame;
    if(frame.size.width<640 || frame.size.height<480) return 3;
    NSString *token=[@"RGPU" stringByAppendingString:[[NSString stringWithUTF8String:argv[2]] uppercaseString]];
    ViewportWindow *window=[[ViewportWindow alloc] initWithContentRect:frame styleMask:NSWindowStyleMaskBorderless
                                                  backing:NSBackingStoreBuffered defer:NO];
    window.level=NSFloatingWindowLevel;window.title=@"Raphael viewport input qualification";
    ViewportView *view=[[ViewportView alloc] initWithFrame:NSMakeRect(0,0,frame.size.width,frame.size.height)];
    view.token=token;
    CGFloat width=frame.size.width,height=frame.size.height;
    view.targets=@[[NSValue valueWithPoint:NSMakePoint(width*.08,height*.08)],
                   [NSValue valueWithPoint:NSMakePoint(width*.92,height*.08)],
                   [NSValue valueWithPoint:NSMakePoint(width*.92,height*.92)],
                   [NSValue valueWithPoint:NSMakePoint(width*.08,height*.92)],
                   [NSValue valueWithPoint:NSMakePoint(width*.5,height*.5)]];
    window.contentView=view;
    NSTextField *field=[[NSTextField alloc] initWithFrame:NSMakeRect(width*.5-200,height*.5+48,400,40)];
    field.placeholderString=@"Keyboard check after five targets";field.hidden=YES;
    [view addSubview:field];
    [window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
    CGDirectDisplayID target=[screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
    NSDictionary *baseline=targetSnapshot(target,window,view);
    if(!target || ![baseline[@"target_present"] boolValue] || ![baseline[@"online"] boolValue] ||
       ![baseline[@"mode_present"] boolValue]) return 3;
    __block NSUInteger geometryChanges=0;
    NSMutableArray *clicks=[NSMutableArray array];
    NSMutableArray *screenChanges=[NSMutableArray array];
    __block NSString *lastText=@"";__block NSUInteger missed=0;
    __block BOOL finished=NO;double started=NSProcessInfo.processInfo.systemUptime;
    void (^publish)(void)=^{
        NSPoint p=view.step<5 ? view.targets[view.step].pointValue : NSMakePoint(width*.5,height*.5+68);
        NSDictionary *state=@{@"token":token,@"step":@(view.step),@"missed":@(missed),
            @"logical_size":@[@(width),@(height)],@"backing_scale":@(screen.backingScaleFactor),
            @"target_top_left":@[@(p.x),@(p.y)],@"text":field.stringValue,
            @"screen_changes":screenChanges,@"geometry_changes":@(geometryChanges),
            @"baseline_target":baseline,@"current_target":targetSnapshot(target,window,view),@"uptime":@(NSProcessInfo.processInfo.systemUptime)};
        if(!saveJSON(ready,state)) _exit(5);
    };
    id monitor=[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskLeftMouseDown
        handler:^NSEvent *(NSEvent *event) {
            if(event.window!=window || finished) return event;
            NSPoint actual=[view convertPoint:event.locationInWindow fromView:nil];
            NSUInteger step=view.step;BOOL hit=NO;
            if(step<5) {
                NSPoint expected=view.targets[step].pointValue;
                hit=fabs(actual.x-expected.x)<=24 && fabs(actual.y-expected.y)<=24;
                if(hit) view.step++; else missed++;
            }
            [clicks addObject:@{@"step":@(step),@"point_top_left":@[@(actual.x),@(actual.y)],
                               @"hit":@(hit),@"uptime":@(NSProcessInfo.processInfo.systemUptime)}];
            if(view.step==5) { field.hidden=NO;[window makeFirstResponder:field]; }
            [view setNeedsDisplay:YES];publish();return event;
        }];
    id screenObserver=[NSNotificationCenter.defaultCenter
        addObserverForName:NSApplicationDidChangeScreenParametersNotification object:nil queue:NSOperationQueue.mainQueue
        usingBlock:^(NSNotification *notification) {
            (void)notification;NSScreen *now=NSScreen.mainScreen;
            NSDictionary *observed=targetSnapshot(target,window,view);
            BOOL changed=![observed isEqualToDictionary:baseline];
            if(changed)geometryChanges++;
            [screenChanges addObject:@{@"uptime":@(NSProcessInfo.processInfo.systemUptime),
                @"logical_size":@[@(now.frame.size.width),@(now.frame.size.height)],
                @"backing_scale":@(now.backingScaleFactor),@"target":observed,
                @"geometry_or_identity_changed":@(changed)}];publish();
        }];
    publish();
    NSTimer *timer=[NSTimer scheduledTimerWithTimeInterval:.1 repeats:YES block:^(NSTimer *tick) {
        if(![lastText isEqualToString:field.stringValue]) { lastText=[field.stringValue copy];publish(); }
        BOOL complete=view.step==5 && [field.stringValue isEqualToString:token];
        BOOL timedOut=NSProcessInfo.processInfo.systemUptime-started>=duration;
        if(!complete && !timedOut) return;
        finished=YES;[tick invalidate];
        NSDictionary *finalTarget=targetSnapshot(target,window,view);
        BOOL finalUnchanged=[finalTarget isEqualToDictionary:baseline];
        BOOL passed=complete && missed==0 && geometryChanges==0 && finalUnchanged;
        NSDictionary *value=@{@"passed":@(passed),@"complete":@(complete),@"timed_out":@(timedOut),
            @"token":token,@"text":field.stringValue,@"target_hits":@(view.step),@"missed":@(missed),
            @"clicks":clicks,@"screen_changes":screenChanges,@"geometry_changes":@(geometryChanges),
            @"baseline_target":baseline,@"final_target":finalTarget,@"final_target_unchanged":@(finalUnchanged),@"logical_size":@[@(width),@(height)],
            @"backing_scale":@(screen.backingScaleFactor),@"elapsed":@(NSProcessInfo.processInfo.systemUptime-started),
            @"scope":@"Guest input observations only. Host artifacts must prove actual manager resize/input path."};
        BOOL saved=saveJSON(result,value);[NSEvent removeMonitor:monitor];[NSNotificationCenter.defaultCenter removeObserver:screenObserver];
        [window orderOut:nil];
        alarm(0);exit(!saved?5:passed?0:3);
    }];
    (void)timer;[NSApp run];return 0;
}}
