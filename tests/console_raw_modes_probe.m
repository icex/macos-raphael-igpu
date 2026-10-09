// Read-only 24G830 x86_64 SkyLight inventory. Never selects/configures a mode.
// Build: clang -fobjc-arc -framework Foundation -framework CoreGraphics FILE -o probe
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dlfcn.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <math.h>
// ABI proved by callee register saves EDI,RSI,RDX,ECX and caller record stride0xd4.
typedef int32_t (*CountFn)(uint32_t,uint32_t *);
typedef int32_t (*ModesFn)(uint32_t,void *,uint32_t *,uint32_t);
static uint32_t word(const uint8_t *p,unsigned off){uint32_t n;memcpy(&n,p+off,4);return n;}
static BOOL identity(CGDirectDisplayID did){
 return did==4128836&&CGDisplayIsOnline(did)&&CGDisplayVendorNumber(did)==0x5250&&CGDisplayModelNumber(did)==0x3453;
}
int main(int argc,const char **argv){@autoreleasepool{
 (void)argv;if(argc!=1)return 2;alarm(10);
 CGDirectDisplayID ids[32],target=0;uint32_t count=0,matches=0;
 if(CGGetOnlineDisplayList(32,ids,&count)||count>=32)return 3;
 for(unsigned i=0;i<count;i++)if(CGDisplayVendorNumber(ids[i])==0x5250&&CGDisplayModelNumber(ids[i])==0x3453){target=ids[i];matches++;}
 if(matches!=1||!identity(target))return 4;
 void *lib=dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight",RTLD_NOW|RTLD_LOCAL);
 if(!lib)return 5;
 CountFn getCount=(CountFn)dlsym(lib,"SLSGetNumberOfDisplayModes");
 ModesFn getModes=(ModesFn)dlsym(lib,"SLSGetDisplayModeDescriptionsOfLength");
 if(!getCount||!getModes)return 6;
 uint32_t requested=0;if(getCount(target,&requested)||!requested||requested>256)return 7;
 // Fixed bounded capacity tolerates a count increase without an out-of-bounds copy.
 uint8_t records[256][0xd4]={0};uint32_t actual=256;
 int32_t error=getModes(target,records,&actual,0xd4);
 uint32_t after=0;if(error||actual>256||getCount(target,&after)||after!=actual||!identity(target))return 8;
 NSMutableArray *rows=[NSMutableArray new];
 for(unsigned i=0;i<actual;i++){
  const uint8_t *p=records[i];NSMutableString *hex=[NSMutableString new];
  for(unsigned j=0;j<0xd4;j++)[hex appendFormat:@"%02x",p[j]];
  float scale;memcpy(&scale,p+0xd0,4);
  if(!isfinite(scale))return 9;
  [rows addObject:@{@"index":@(i),@"mode_number":@(word(p,0)),@"io_mode_id":@(word(p,0xc4)),
   @"width":@(word(p,8)),@"height":@(word(p,12)),@"pixel_width":@(word(p,0xc8)),@"pixel_height":@(word(p,0xcc)),
   @"resolution":@(scale),@"io_flags":@(word(p,0xc0)),@"raw_hex":hex}];
 }
 CFArrayRef publicModes=CGDisplayCopyAllDisplayModes(target,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
 NSMutableArray *visible=[NSMutableArray new];
 if(publicModes){for(CFIndex i=0;i<CFArrayGetCount(publicModes);i++){
  CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(publicModes,i);
  [visible addObject:@{@"io_mode_id":@(CGDisplayModeGetIODisplayModeID(m)),@"pixel_width":@(CGDisplayModeGetPixelWidth(m)),@"pixel_height":@(CGDisplayModeGetPixelHeight(m))}];
 }CFRelease(publicModes);}
 if(!identity(target))return 10;
 NSDictionary *result=@{@"display":@(target),@"requested_count":@(requested),@"count":@(actual),@"record_bytes":@0xd4,@"records":rows,@"public_modes":visible,
 @"scope":@"Read-only existing display mode descriptors; no selection, configuration or cache mutation; private ABI pinned to decoded24G830 x86_64"};
 NSData *json=[NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:nil];
 if(!json)return 11;fwrite(json.bytes,1,json.length,stdout);putchar('\n');return 0;
}}
