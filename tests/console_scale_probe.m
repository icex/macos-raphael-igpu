// Standalone bounded diagnostic. Enumerates existing modes; optionally selects
// one exact physical/logical pair. Never creates a display or changes its table.
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
static BOOL topology(NSArray *rows,NSArray *before,CGDirectDisplayID target) {
    if(!rows||rows.count!=before.count)return NO;
    for(NSUInteger i=0;i<rows.count;i++) {
        NSDictionary *a=rows[i],*b=before[i];
        if([a[@"display"] unsignedIntValue]!=[b[@"display"] unsignedIntValue])return NO;
        if([a[@"display"] unsignedIntValue]!=target){if(![a isEqual:b])return NO;continue;}
        NSArray *frame=a[@"frame"];
        if(!identity(a)||[frame[0] doubleValue]!=0||[frame[1] doubleValue]!=0||
           [a[@"in_mirror_set"] boolValue]||[a[@"mirrors"] unsignedIntValue]!=kCGNullDirectDisplay)return NO;
        for(NSString *key in @[@"active",@"main",@"rotation"])
            if(![a[key] isEqual:b[key]])return NO;
    }
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
int main(int argc,const char **argv) { @autoreleasepool {
    BOOL select=argc==6&&!strcmp(argv[1],"--select");
    if(!select&&!(argc==2&&!strcmp(argv[1],"--list")))return 2;
    unsigned g[4]={0};
    if(select){
        for(unsigned i=0;i<4;i++){
            const char *p=argv[i+2];if(!*p)return 2;
            for(const char *q=p;*q;q++)if(*q<'0'||*q>'9')return 2;
            char *end=NULL;unsigned long v=strtoul(p,&end,10);
            if(*end||!v||v>3840)return 2;g[i]=(unsigned)v;
        }
        if(g[0]<640||g[1]<480||g[1]>2160||
           !((g[0]==g[2]&&g[1]==g[3])||(g[0]==2*g[2]&&g[1]==2*g[3])))return 2;
    }
    signal(SIGALRM,expired);alarm(8);
    NSArray *before=inventory();CGDirectDisplayID target=0;unsigned matches=0;
    for(NSDictionary *row in before)if(identity(row)){target=[row[@"display"] unsignedIntValue];matches++;}
    NSMutableDictionary *result=[@{@"scope":@"Existing-mode scale diagnostic; no display creation or mode-table mutation",
        @"operation":select?@"select":@"list",@"before_displays":before?:@[],@"matching_displays":@(matches),
        @"requested":@{@"pixel_width":@(g[0]),@"pixel_height":@(g[1]),@"width":@(g[2]),@"height":@(g[3])}} mutableCopy];
    BOOL passed=NO;NSString *reason=@"ambiguous or unavailable target";CGDisplayModeRef chosen=NULL;
    if(before&&matches==1){
        CFArrayRef modes=CGDisplayCopyAllDisplayModes(target,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
        NSMutableArray *all=[NSMutableArray array];
        if(modes&&CFArrayGetCount(modes)<=2048){
            for(CFIndex i=0;i<CFArrayGetCount(modes);i++){
                CGDisplayModeRef mode=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
                [all addObject:modeRow(mode)];
                if(select&&!chosen&&exact(mode,g))chosen=CGDisplayModeRetain(mode);
            }
            passed=!select;reason=select?@"requested exact mode unavailable":@"enumerated";
        }else reason=@"mode inventory unavailable or exceeds bound";
        result[@"modes"]=all;if(modes)CFRelease(modes);
        if(select&&chosen){
            NSArray *preconfigure=inventory();result[@"preconfigure_displays"]=preconfigure?:@[];
            if(!topology(preconfigure,before,target))reason=@"identity or topology refused before configure";
            else {
                CGDisplayConfigRef config=NULL;CGError e=CGBeginDisplayConfiguration(&config);
                if(!e){e=CGConfigureDisplayWithDisplayMode(config,target,chosen,NULL);
                    if(!e)e=CGCompleteDisplayConfiguration(config,kCGConfigureForSession);else CGCancelDisplayConfiguration(config);}
                result[@"configure_error"]=@(e);reason=@"configure failed";
                if(!e){
                    double deadline=now()+4,stable=-1;NSMutableArray *samples=[NSMutableArray array];reason=@"settle deadline";
                    while(now()<deadline){
                        NSArray *observed=inventory();CGDisplayModeRef current=CGDisplayCopyDisplayMode(target);
                        BOOL ready=topology(observed,before,target)&&exact(current,g);
                        [samples addObject:@{@"uptime":@(now()),@"ready":@(ready),@"target":displayRow(target)}];
                        if(current)CGDisplayModeRelease(current);
                        if(!ready)stable=-1;else if(stable<0)stable=now();
                        if(ready&&now()-stable>=.2){passed=YES;reason=@"exact mode settled";break;}
                        if(samples.count>=100){reason=@"sample bound";break;}
                        [NSThread sleepForTimeInterval:MIN(.05,MAX(0,deadline-now()))];
                    }
                    result[@"settle_samples"]=samples;
                }
            }
        }
    }
    if(chosen)CGDisplayModeRelease(chosen);
    NSArray *after=inventory();result[@"after_displays"]=after?:@[];
    if(!after){passed=NO;reason=@"final inventory unavailable";}
    if(matches==1){
        CFArrayRef modes=CGDisplayCopyAllDisplayModes(target,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
        NSMutableArray *rows=[NSMutableArray array];
        if(modes&&CFArrayGetCount(modes)<=2048){
            for(CFIndex i=0;i<CFArrayGetCount(modes);i++)[rows addObject:modeRow((CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i))];
        }else {passed=NO;reason=@"final modes unavailable or exceeds bound";}
        result[@"after_modes"]=rows;if(modes)CFRelease(modes);
    }
    if(passed&&select){
        CGDisplayModeRef final=CGDisplayCopyDisplayMode(target);
        if(!topology(after,before,target)||!exact(final,g)){passed=NO;reason=@"final readback changed";}
        if(final)CGDisplayModeRelease(final);
    }
    result[@"passed"]=@(passed);result[@"reason"]=reason;result[@"target_display"]=@(target);
    alarm(0);return output(result,passed);
}}
