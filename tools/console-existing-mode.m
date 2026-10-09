// Existing-mode control only. No virtual display creation, capture or TCC APIs.
// clang -O2 -Wall -Wextra -framework Foundation -framework CoreGraphics source.m -o helper
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <signal.h>
#include <unistd.h>
#include <stdlib.h>
#include <errno.h>
static void expired(int sig) {(void)sig;_exit(124);}
static void emit(NSDictionary *row) {
 NSData *data=[NSJSONSerialization dataWithJSONObject:row options:0 error:nil];
 fwrite(data.bytes,1,data.length,stdout);putchar('\n');
}
static NSDictionary *info(CGDisplayModeRef m) {
 return @{@"width":@(CGDisplayModeGetWidth(m)),@"height":@(CGDisplayModeGetHeight(m)),
          @"pixel_width":@(CGDisplayModeGetPixelWidth(m)),@"pixel_height":@(CGDisplayModeGetPixelHeight(m)),
          @"mode_id":@(CGDisplayModeGetIODisplayModeID(m)),@"refresh":@(CGDisplayModeGetRefreshRate(m))};
}
static bool number(const char *s,unsigned *value) {
 char *end=NULL;errno=0;unsigned long n=strtoul(s,&end,10);
 if(errno||!s[0]||*end||n>3840)return false;*value=(unsigned)n;return true;
}
int main(int argc,char **argv) {@autoreleasepool {
 signal(SIGALRM,expired);alarm(5);
 bool apply=argc==4&&!strcmp(argv[1],"--set");unsigned w=0,h=0;
 if(!(argc==2&&!strcmp(argv[1],"--list")) && !apply)return 2;
 if(apply&&(!number(argv[2],&w)||!number(argv[3],&h)||w<320||h<200||h>2160))return 2;
 CGDirectDisplayID ids[64],target=0;uint32_t n=0;
 if(CGGetOnlineDisplayList(64,ids,&n)!=kCGErrorSuccess||n>=64)return 3;
 for(unsigned i=0;i<n;i++)if(CGDisplayVendorNumber(ids[i])==0x5250&&CGDisplayModelNumber(ids[i])==0x3453){if(target)return 3;target=ids[i];}
 if(!target)return 3;
 CGRect beforeBounds=CGDisplayBounds(target);
 if(apply&&(beforeBounds.origin.x!=0||beforeBounds.origin.y!=0)){emit(@{@"passed":@NO,@"reason":@"target-origin-not-zero"});return 4;}
 CFArrayRef modes=CGDisplayCopyAllDisplayModes(target,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
 if(!modes)return 3;
 NSMutableArray *list=[NSMutableArray new];CGDisplayModeRef choice=NULL;bool bestHi=false;
 for(CFIndex i=0;i<CFArrayGetCount(modes);i++){
  CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);[list addObject:info(m)];
  if(CGDisplayModeGetPixelWidth(m)!=w||CGDisplayModeGetPixelHeight(m)!=h)continue;
  bool hi=CGDisplayModeGetWidth(m)*2==w&&CGDisplayModeGetHeight(m)*2==h;
  if(!choice||(hi&&!bestHi)){choice=m;bestHi=hi;}
 }
 if(!apply){emit(@{@"display":@(target),@"modes":list});CFRelease(modes);return 0;}
 if(!choice){emit(@{@"passed":@NO,@"reason":@"no-existing-exact-physical-mode"});CFRelease(modes);return 4;}
 CGError error=CGDisplaySetDisplayMode(target,choice,NULL);
 CGDisplayModeRef actual=CGDisplayCopyDisplayMode(target);
 CGRect afterBounds=CGDisplayBounds(target);
 bool passed=afterBounds.origin.x==0&&afterBounds.origin.y==0&&error==kCGErrorSuccess&&actual&&CGDisplayModeGetPixelWidth(actual)==w&&CGDisplayModeGetPixelHeight(actual)==h&&CGDisplayVendorNumber(target)==0x5250&&CGDisplayModelNumber(target)==0x3453;
 NSMutableDictionary *actualInfo=actual?[info(actual) mutableCopy]:[NSMutableDictionary new];
 actualInfo[@"origin_x"]=@(afterBounds.origin.x);actualInfo[@"origin_y"]=@(afterBounds.origin.y);
 emit(@{@"passed":@(passed),@"display":@(target),@"error":@(error),@"selected":info(choice),@"actual":actualInfo,@"scope":@"existing virtual display mode and zero origin only; no DPI changes"});
 if(actual)CFRelease(actual);CFRelease(modes);return passed?0:5;
}}
