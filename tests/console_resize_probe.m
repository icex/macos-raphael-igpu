// Select one exact virtual-console mode; never change a physical display mode.
#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#include <signal.h>
#include <unistd.h>
static void expired(int signal) { _exit(124); }
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired);alarm(20);[NSApplication sharedApplication];
    if(argc!=4)return 2;
    unsigned w=atoi(argv[1]),h=atoi(argv[2]),scale=atoi(argv[3]);
    if(w<640||w>1920||h<480||h>1152||(scale!=1&&scale!=2))return 2;
    CGDirectDisplayID ids[32],target=0;uint32_t n=0;
    if(CGGetOnlineDisplayList(32,ids,&n))return 3;
    for(unsigned i=0;i<n;i++)if(CGDisplayVendorNumber(ids[i])==0x5250&&CGDisplayModelNumber(ids[i])==0x3453) {
        if(target)return 3;target=ids[i];
    }
    if(!target)return 3;
    CFArrayRef modes=CGDisplayCopyAllDisplayModes(target,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
    CGError result=kCGErrorIllegalArgument;
    if(modes)for(CFIndex i=0;i<CFArrayGetCount(modes);i++) {
        CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
        if(CGDisplayModeGetWidth(m)==w&&CGDisplayModeGetHeight(m)==h&&
           CGDisplayModeGetPixelWidth(m)==w*scale&&CGDisplayModeGetPixelHeight(m)==h*scale) {
            result=CGDisplaySetDisplayMode(target,m,NULL);break;
        }
    }
    if(modes)CFRelease(modes);
    CGDisplayModeRef current=CGDisplayCopyDisplayMode(target);
    if(!current)return 4;
    BOOL match=CGDisplayModeGetWidth(current)==w&&CGDisplayModeGetHeight(current)==h&&
        CGDisplayModeGetPixelWidth(current)==w*scale&&CGDisplayModeGetPixelHeight(current)==h*scale;
    printf("CONSOLE_RESIZE display=%u result=%d logical=%zux%zu pixels=%zux%zu matched=%d\n",target,result,
        CGDisplayModeGetWidth(current),CGDisplayModeGetHeight(current),
        CGDisplayModeGetPixelWidth(current),CGDisplayModeGetPixelHeight(current),match);
    CFRelease(current);return result==kCGErrorSuccess&&match?0:4;
}}
