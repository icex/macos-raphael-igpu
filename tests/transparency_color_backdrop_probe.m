#import <AppKit/AppKit.h>
#include <unistd.h>
#include <signal.h>
static int phase;
@interface ColorView:NSView
@end
@implementation ColorView
-(void)drawRect:(NSRect)r{(void)r;for(int y=0;y<600;y+=20)for(int x=0;x<1000;x+=20){[[NSColor colorWithCalibratedRed:((x/20+phase)%17)/16.0 green:((y/20+phase)%13)/12.0 blue:((x/20+y/20)%11)/10.0 alpha:1]setFill];NSRectFill(NSMakeRect(x,y,20,20));}}
@end
int main(int argc,const char**argv){@autoreleasepool{alarm(80);
 if(geteuid()==0){NSTask*t=[NSTask new];t.launchPath=@"/bin/launchctl";NSString*cmd=[NSString stringWithFormat:@"%s --child",argv[0]];t.arguments=@[@"asuser",@"501",@"/usr/bin/su",@"-l",@"bogdan",@"-c",cmd];[t launch];[t waitUntilExit];return t.terminationStatus;}
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
 NSWindow*back=[[NSWindow alloc]initWithContentRect:NSMakeRect(60,140,1040,640) styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];back.contentView=[[ColorView alloc]initWithFrame:NSMakeRect(0,0,1040,640)];[back orderFront:nil];
 NSWindow*w=[[NSWindow alloc]initWithContentRect:NSMakeRect(80,160,1000,600) styleMask:NSWindowStyleMaskTitled|NSWindowStyleMaskClosable backing:NSBackingStoreBuffered defer:NO];w.title=@"Raphael transparency diagnostic — colored moving backdrop";w.appearance=[NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];w.backgroundColor=[NSColor clearColor];w.opaque=NO;
 NSView*v=[[NSView alloc]initWithFrame:NSMakeRect(0,0,1000,600)];w.contentView=v;
 NSVisualEffectMaterial materials[]={NSVisualEffectMaterialPopover,NSVisualEffectMaterialMenu,NSVisualEffectMaterialSidebar,NSVisualEffectMaterialHUDWindow};
 for(int i=0;i<4;i++){NSVisualEffectView*e=[[NSVisualEffectView alloc]initWithFrame:NSMakeRect(25+245*i,60,220,500)];e.material=materials[i];e.blendingMode=NSVisualEffectBlendingModeBehindWindow;e.state=NSVisualEffectStateActive;[v addSubview:e];}
 [w makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];printf("WINDOW_READY %.0f %.0f %.0f %.0f\n",w.frame.origin.x,w.frame.origin.y,w.frame.size.width,w.frame.size.height);fflush(stdout);
 NSDate*until=[NSDate dateWithTimeIntervalSinceNow:45];while(until.timeIntervalSinceNow>0){NSEvent*e=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate dateWithTimeIntervalSinceNow:.05] inMode:NSDefaultRunLoopMode dequeue:YES];if(e)[NSApp sendEvent:e];phase++;[back.contentView setNeedsDisplay:YES];[NSApp updateWindows];} [w orderOut:nil];[back orderOut:nil];return 0;}}
