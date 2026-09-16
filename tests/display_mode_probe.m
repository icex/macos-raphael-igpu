#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s){(void)s;_exit(124);}
static NSDictionary *mode(CGDisplayModeRef m) {return m?@{@"width":@(CGDisplayModeGetWidth(m)),@"height":@(CGDisplayModeGetHeight(m)),@"pixel_width":@(CGDisplayModeGetPixelWidth(m)),@"pixel_height":@(CGDisplayModeGetPixelHeight(m)),@"refresh":@(CGDisplayModeGetRefreshRate(m)),@"id":@(CGDisplayModeGetIODisplayModeID(m))}:@{};}
int main(int argc,const char **argv) {@autoreleasepool {
 signal(SIGALRM,expired);alarm(20);[NSApplication sharedApplication];
 if(argc!=2)return 2;double hz=atof(argv[1]);if(hz!=0&&hz!=60&&hz!=90&&hz!=120)return 2;
 CGDirectDisplayID d=CGMainDisplayID();CFArrayRef all=CGDisplayCopyAllDisplayModes(d,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
 NSMutableArray *rows=[NSMutableArray new];CGDisplayModeRef target=NULL;
 if(all)for(CFIndex i=0;i<CFArrayGetCount(all);i++){CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(all,i);[rows addObject:mode(m)];if(CGDisplayModeGetWidth(m)==1920&&CGDisplayModeGetHeight(m)==1080&&CGDisplayModeGetPixelWidth(m)==3840&&CGDisplayModeGetPixelHeight(m)==2160&&CGDisplayModeGetRefreshRate(m)==hz)target=m;}
 CGError result=kCGErrorSuccess;if(hz>0)result=target?CGDisplaySetDisplayMode(d,target,NULL):kCGErrorIllegalArgument;
 CGDisplayModeRef current=CGDisplayCopyDisplayMode(d);NSMutableArray *screens=[NSMutableArray new];for(NSScreen *s in NSScreen.screens)[screens addObject:@{@"id":s.deviceDescription[@"NSScreenNumber"],@"width":@(s.frame.size.width),@"height":@(s.frame.size.height),@"scale":@(s.backingScaleFactor)}];
 NSDictionary *j=@{@"display_id":@(d),@"modes":rows,@"current":mode(current),@"requested_hz":@(hz),@"select_result":@(result),@"screens":screens};NSData *data=[NSJSONSerialization dataWithJSONObject:j options:0 error:nil];fwrite(data.bytes,1,data.length,stdout);putchar('\n');if(current)CFRelease(current);if(all)CFRelease(all);return result==kCGErrorSuccess?0:3;
}}
