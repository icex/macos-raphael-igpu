// Bounded raw valid-mode diagnostic. Explicit --select-raw-20 only.
// Uses existing mode20 for3840x2160 at1x; never creates or changes a mode table.
// Build: clang -fobjc-arc -framework Foundation -framework CoreGraphics ...
// Usage: console-scale-probe --list
//        console-scale-probe --select pixelW pixelH logicalW logicalH
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <stdio.h>
#include <signal.h>
#include <unistd.h>
#include <time.h>
#include <stdlib.h>
#include <string.h>

static void expired(int n) {(void)n;_exit(124);}
static double now(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static NSDictionary *modeRow(CGDisplayModeRef mode) {
    if(!mode)return @{};
    return @{@"mode_id":@(CGDisplayModeGetIODisplayModeID(mode)),
        @"pixel_width":@(CGDisplayModeGetPixelWidth(mode)),@"pixel_height":@(CGDisplayModeGetPixelHeight(mode)),
        @"width":@(CGDisplayModeGetWidth(mode)),@"height":@(CGDisplayModeGetHeight(mode)),
        @"refresh_hz":@(CGDisplayModeGetRefreshRate(mode))};
}
static NSDictionary *displayRow(CGDirectDisplayID did) {
    CGRect b=CGDisplayBounds(did);CGDisplayModeRef mode=CGDisplayCopyDisplayMode(did);
    NSDictionary *row=@{@"display":@(did),@"vendor":@(CGDisplayVendorNumber(did)),
        @"model":@(CGDisplayModelNumber(did)),@"serial":@(CGDisplaySerialNumber(did)),
        @"online":@(CGDisplayIsOnline(did)),@"active":@(CGDisplayIsActive(did)),
        @"main":@(CGDisplayIsMain(did)),@"in_mirror_set":@(CGDisplayIsInMirrorSet(did)),
        @"mirrors":@(CGDisplayMirrorsDisplay(did)),@"rotation":@(CGDisplayRotation(did)),
        @"frame":@[@(b.origin.x),@(b.origin.y),@(b.size.width),@(b.size.height)],@"mode":modeRow(mode)};
    if(mode)CGDisplayModeRelease(mode);return row;
}
static NSArray *inventory(void) {
    CGDirectDisplayID ids[64];uint32_t count=0,total=0;
    if(CGGetOnlineDisplayList(0,NULL,&total)!=kCGErrorSuccess||!total||total>64)return nil;
    if(CGGetOnlineDisplayList(64,ids,&count)!=kCGErrorSuccess||count!=total)return nil;
    NSMutableArray *rows=[NSMutableArray array];
    for(uint32_t i=0;i<count;i++)[rows addObject:displayRow(ids[i])];
    [rows sortUsingComparator:^NSComparisonResult(NSDictionary *a,NSDictionary *b){return [a[@"display"] compare:b[@"display"]];}];
    return rows;
}
static BOOL identity(NSDictionary *row) {
    return [row[@"online"] boolValue]&&[row[@"vendor"] unsignedIntValue]==0x5250&&
        [row[@"model"] unsignedIntValue]==0x3453&&[row[@"serial"] unsignedIntValue]==0x34530001;
}
static BOOL topology(NSArray *rows,NSArray *before,CGDirectDisplayID target,
                     BOOL postconfigure,NSMutableArray *allowedMirrorChanges) {
    if(!rows||rows.count!=before.count)return NO;
    NSMutableArray *changes=[NSMutableArray array];
    for(NSUInteger i=0;i<rows.count;i++) {
        NSDictionary *a=rows[i],*b=before[i];
        if([a[@"display"] unsignedIntValue]!=[b[@"display"] unsignedIntValue])return NO;
        if([a[@"display"] unsignedIntValue]!=target){
            // Only an existing destination of this exact source may adapt its
            // mode/frame size after our configuration. Never permit rewiring,
            // origin movement, identity changes, or unrelated display changes.
            BOOL destination=postconfigure&&[a[@"mirrors"] unsignedIntValue]==target&&
                [b[@"mirrors"] unsignedIntValue]==target;
            if(destination){
                NSMutableDictionary *fixedA=[a mutableCopy],*fixedB=[b mutableCopy];
                [fixedA removeObjectForKey:@"mode"];[fixedB removeObjectForKey:@"mode"];
                NSArray *af=a[@"frame"],*bf=b[@"frame"];
                fixedA[@"frame"]=@[af[0],af[1]];fixedB[@"frame"]=@[bf[0],bf[1]];
                if(![fixedA isEqual:fixedB])return NO;
                if(![a isEqual:b])[changes addObject:@{@"display":a[@"display"],
                    @"before_mode":b[@"mode"],@"after_mode":a[@"mode"],
                    @"before_frame":bf,@"after_frame":af}];
            }else if(![a isEqual:b])return NO;
            continue;
        }
        NSArray *frame=a[@"frame"];
        if(!identity(a)||[frame[0] doubleValue]!=0||[frame[1] doubleValue]!=0||
           [a[@"mirrors"] unsignedIntValue]!=kCGNullDirectDisplay)return NO;
        // The installed layout uses Raphael as the mirror SOURCE. Membership
        // is allowed only unchanged; a mirrored destination remains refused.
        for(NSString *key in @[@"active",@"main",@"rotation",@"in_mirror_set"])
            if(![a[key] isEqual:b[key]])return NO;
    }
    [allowedMirrorChanges addObjectsFromArray:changes];
    return YES;
}
static BOOL exact(CGDisplayModeRef m,const unsigned *g) {
    return m&&CGDisplayModeGetPixelWidth(m)==g[0]&&CGDisplayModeGetPixelHeight(m)==g[1]&&
        CGDisplayModeGetWidth(m)==g[2]&&CGDisplayModeGetHeight(m)==g[3];
}
static int output(NSDictionary *row,BOOL passed) {
    NSData *data=[NSJSONSerialization dataWithJSONObject:row options:NSJSONWritingPrettyPrinted error:nil];
    if(!data)return 5;
    fwrite(data.bytes,1,data.length,stdout);putchar('\n');fflush(stdout);return passed?0:3;
}
#include <dlfcn.h>
typedef int32_t (*RawCount)(uint32_t,uint32_t *);
typedef int32_t (*RawModes)(uint32_t,void *,uint32_t *,uint32_t);
typedef int32_t (*RawConfigure)(CGDisplayConfigRef,uint32_t,uint32_t);
static uint32_t rawword(const uint8_t *p,unsigned offset){uint32_t v;memcpy(&v,p+offset,4);return v;}
static BOOL rawCandidate(RawCount count,RawModes modes,CGDirectDisplayID target,uint8_t chosen[212]){
 uint32_t n=0;if(count(target,&n)||!n||n>256)return NO;
 uint8_t records[256][212]={0};uint32_t capacity=256;
 if(modes(target,records,&capacity,212)||capacity>256)return NO;
 unsigned found=0;
 for(unsigned i=0;i<capacity;i++){
  const uint8_t *p=records[i];float scale;memcpy(&scale,p+208,4);
  if(rawword(p,0)==20&&rawword(p,196)==20&&rawword(p,8)==3840&&rawword(p,12)==2160&&
     rawword(p,200)==3840&&rawword(p,204)==2160&&rawword(p,192)==3&&scale==1.0f){memcpy(chosen,p,212);found++;}
 }
 return found==1;
}
int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=2||strcmp(argv[1],"--select-raw-20"))return 2;
 signal(SIGALRM,expired);alarm(8);
 const CGDirectDisplayID target=4128836;unsigned g[4]={3840,2160,3840,2160};
 NSArray *before=inventory();unsigned matches=0;
 for(NSDictionary *row in before)if(identity(row)){if([row[@"display"] unsignedIntValue]!=target)return 3;matches++;}
 if(!before||matches!=1||!topology(before,before,target,NO,nil))return 3;
 void *lib=dlopen("/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight",RTLD_NOW|RTLD_LOCAL);
 if(!lib)return 4;
 RawCount count=(RawCount)dlsym(lib,"SLSGetNumberOfDisplayModes");
 RawModes modes=(RawModes)dlsym(lib,"SLSGetDisplayModeDescriptionsOfLength");
 RawConfigure configure=(RawConfigure)dlsym(lib,"SLSConfigureDisplayMode");
 if(!lib||!count||!modes||!configure)return 4;
 uint8_t first[212],second[212];if(!rawCandidate(count,modes,target,first))return 5;
 NSArray *pre=inventory();
 if(!topology(pre,before,target,NO,nil)||!rawCandidate(count,modes,target,second)||memcmp(first,second,212))return 6;
 CGDisplayConfigRef config=NULL;CGError e=CGBeginDisplayConfiguration(&config);
 if(!e){e=configure(config,target,20);if(!e)e=CGCompleteDisplayConfiguration(config,kCGConfigureForSession);else CGCancelDisplayConfiguration(config);}
 BOOL passed=NO;double deadline=now()+4,stable=-1;NSMutableArray *samples=[NSMutableArray new];
 if(!e)while(now()<deadline&&samples.count<100){
  NSArray *observed=inventory();CGDisplayModeRef current=CGDisplayCopyDisplayMode(target);
  NSMutableArray *adapt=[NSMutableArray new];BOOL ready=topology(observed,before,target,YES,adapt)&&exact(current,g);
  [samples addObject:@{@"uptime":@(now()),@"ready":@(ready),@"target":displayRow(target),@"allowed_mirror_mode_changes":adapt}];
  if(current)CGDisplayModeRelease(current);
  if(!ready)stable=-1;else if(stable<0)stable=now();
  if(ready&&now()-stable>=.2){passed=YES;break;}
  [NSThread sleepForTimeInterval:.05];
 }
 NSArray *after=inventory();CGDisplayModeRef final=CGDisplayCopyDisplayMode(target);
 passed=passed&&topology(after,before,target,YES,nil)&&exact(final,g);if(final)CGDisplayModeRelease(final);
 NSDictionary *result=@{@"passed":@(passed),@"configure_error":@(e),@"target_display":@(target),@"raw_mode_number":@20,
  @"before_displays":before,@"after_displays":after?:@[],@"settle_samples":samples,
  @"scope":@"One existing raw-valid3840x2160 1x mode; public begin/session complete plus private SLSConfigureDisplayMode; no table or serial mutation"};
 alarm(0);return output(result,passed);
}}
