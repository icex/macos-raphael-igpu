#import <AppKit/AppKit.h>

// Live console qualification, separate from the hardware launch harness.
// Result includes exact received text and window-local mouse coordinates.
static void save(NSString *path, NSDictionary *value) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:path atomically:YES];
}
int main(int argc,const char **argv) { @autoreleasepool {
    if(argc!=2)return 2;
    NSString *prefix=[NSString stringWithUTF8String:argv[1]];
    NSApplication *app=[NSApplication sharedApplication];
    [app setActivationPolicy:NSApplicationActivationPolicyRegular];
    NSWindow *w=[[NSWindow alloc] initWithContentRect:NSMakeRect(200,200,600,260)
        styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];
    w.title=@"Raphael console input qualification";
    NSTextField *field=[[NSTextField alloc] initWithFrame:NSMakeRect(40,110,520,40)];
    field.placeholderString=@"Console keyboard test";
    [w.contentView addSubview:field];[w makeKeyAndOrderFront:nil];
    [app activateIgnoringOtherApps:YES];[w makeFirstResponder:field];
    __block NSPoint click=NSMakePoint(-1,-1);__block NSUInteger clicks=0;
    id monitor=[NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskLeftMouseDown handler:^NSEvent *(NSEvent *e){
        if(e.window==w){click=e.locationInWindow;clicks++;}return e;
    }];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,2*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        NSRect screen=w.screen.frame;
        NSPoint target=[w convertPointToScreen:NSMakePoint(300,130)];
        save([prefix stringByAppendingString:@"-ready.json"],@{
            @"screen":@[@(screen.origin.x),@(screen.origin.y),@(screen.size.width),@(screen.size.height)],
            @"target":@[@(target.x),@(NSMaxY(screen)-target.y)],@"expected":@"RGPU341"});
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,90*NSEC_PER_SEC),dispatch_get_main_queue(),^{
        BOOL passed=[field.stringValue isEqualToString:@"RGPU341"]&&clicks>0&&
            NSPointInRect(click,field.frame);
        save([prefix stringByAppendingString:@"-result.json"],@{@"passed":@(passed),
            @"text":field.stringValue,@"clicks":@(clicks),@"mouse":@[@(click.x),@(click.y)]});
        [NSEvent removeMonitor:monitor];exit(passed?0:3);
    });
    [app run];return 0;
}}
