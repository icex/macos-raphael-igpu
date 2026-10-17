// Configure the macOS headless fallback for 1080p HiDPI (4K backing).
// Private SPI is ABI-guarded; this is not a physical-display or refresh-rate driver.
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <dispatch/dispatch.h>
#include <stdio.h>
#include <signal.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width height:(unsigned int)height
                   refreshRate:(double)refreshRate;
@end
@interface CGVirtualDisplaySettings : NSObject
@property(copy) NSArray *modes;
@property unsigned int hiDPI;
@property unsigned int rotation;
@end
@interface CGVirtualDisplayDescriptor : NSObject
@property unsigned int vendorID, productID, serialNum, maxPixelsWide, maxPixelsHigh;
@property(copy) NSString *name;
@property CGSize sizeInMillimeters;
@property CGPoint redPrimary, greenPrimary, bluePrimary, whitePoint;
@property(strong) id queue;
@property(copy) id terminationHandler;
@property unsigned int serialNumber;
@end
@interface CGVirtualDisplay : NSObject
@property(readonly) CGDirectDisplayID displayID;
- (instancetype)initWithDescriptor:(id)descriptor;
- (BOOL)applySettings:(id)settings;
@end

static void expired(int s) {(void)s;_exit(124);}
static void emit(NSDictionary *d) {
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes,1,j.length,stdout);putchar('\n');fflush(stdout);
}
static NSArray *inventory(void) {
    CGDirectDisplayID ids[32];uint32_t n=0;
    if(CGGetOnlineDisplayList(32,ids,&n)!=kCGErrorSuccess)return nil;
    NSMutableArray *a=[NSMutableArray new];
    for(unsigned i=0;i<n;i++) {
        CGDisplayModeRef m=CGDisplayCopyDisplayMode(ids[i]);
        if(!m){[a addObject:@{@"id":@(ids[i]),@"mode_unavailable":@YES,@"active":@(CGDisplayIsActive(ids[i])!=0),@"online":@(CGDisplayIsOnline(ids[i])!=0)}];continue;}
        CGRect b=CGDisplayBounds(ids[i]);
        [a addObject:@{@"id":@(ids[i]),@"main":@(CGDisplayIsMain(ids[i])!=0),
            @"active":@(CGDisplayIsActive(ids[i])!=0),@"vendor":@(CGDisplayVendorNumber(ids[i])),
            @"model":@(CGDisplayModelNumber(ids[i])),@"width":@(CGDisplayModeGetWidth(m)),
            @"height":@(CGDisplayModeGetHeight(m)),@"pixel_width":@(CGDisplayModeGetPixelWidth(m)),
            @"pixel_height":@(CGDisplayModeGetPixelHeight(m)),@"refresh":@(CGDisplayModeGetRefreshRate(m)),
            @"x":@(b.origin.x),@"y":@(b.origin.y)}];CFRelease(m);
    }
    return a;
}
static bool signature(NSString *className,NSString *selector,const char *result,NSArray *args) {
    NSMethodSignature *s=[NSClassFromString(className) instanceMethodSignatureForSelector:NSSelectorFromString(selector)];
    if(!s||strcmp(s.methodReturnType,result)||s.numberOfArguments!=args.count+2) {
        emit(@{@"phase":@"abi_error",@"class":className,@"selector":selector,
            @"actual_return":s?@(s.methodReturnType):@"missing",@"expected_return":@(result)});return false;
    }
    for(NSUInteger i=0;i<args.count;i++)if(strcmp([s getArgumentTypeAtIndex:i+2],[args[i] UTF8String]))return false;
    return true;
}
static bool abi(void) {
    for(NSString *s in @[@"setVendorID:",@"setProductID:",@"setSerialNum:",@"setSerialNumber:",@"setMaxPixelsWide:",@"setMaxPixelsHigh:"])
        if(!signature(@"CGVirtualDisplayDescriptor",s,@encode(void),@[@(@encode(unsigned int))]))return false;
    for(NSString *s in @[@"setHiDPI:",@"setRotation:"])
        if(!signature(@"CGVirtualDisplaySettings",s,@encode(void),@[@(@encode(unsigned int))]))return false;
    for(NSString *s in @[@"setWhitePoint:",@"setRedPrimary:",@"setGreenPrimary:",@"setBluePrimary:"])
        if(!signature(@"CGVirtualDisplayDescriptor",s,@encode(void),@[@(@encode(CGPoint))]))return false;
    for(NSString *s in @[@"setName:",@"setQueue:"])
        if(!signature(@"CGVirtualDisplayDescriptor",s,@encode(void),@[@"@"]))return false;
    return signature(@"CGVirtualDisplayDescriptor",@"setSizeInMillimeters:",@encode(void),@[@(@encode(CGSize))]) &&
        signature(@"CGVirtualDisplayMode",@"initWithWidth:height:refreshRate:","@",@[@(@encode(unsigned int)),@(@encode(unsigned int)),@(@encode(double))]) &&
        signature(@"CGVirtualDisplay",@"initWithDescriptor:","@",@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"applySettings:",@encode(BOOL),@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"displayID",@encode(unsigned int),@[]) &&
        signature(@"CGVirtualDisplaySettings",@"setModes:",@encode(void),@[@"@"]);
}
static void pump(double seconds) {
    NSDate *until=[NSDate dateWithTimeIntervalSinceNow:seconds];
    while(until.timeIntervalSinceNow>0)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
}
static bool selectMode(size_t w,size_t h,size_t pw,size_t ph) {
    CGDirectDisplayID displayID=CGMainDisplayID();
    CFArrayRef modes=CGDisplayCopyAllDisplayModes(displayID,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
    bool selected=false;
    if(modes)for(CFIndex i=0;i<CFArrayGetCount(modes);i++) {
        CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
        if(CGDisplayModeGetWidth(m)==w&&CGDisplayModeGetHeight(m)==h&&CGDisplayModeGetPixelWidth(m)==pw&&CGDisplayModeGetPixelHeight(m)==ph&&CGDisplayModeGetRefreshRate(m)==60) {
            selected=CGDisplaySetDisplayMode(displayID,m,NULL)==kCGErrorSuccess;break;
        }
    }
    if(modes)CFRelease(modes);return selected;
}
static bool fallback(NSArray *a) {
    return a.count==1&&[a[0][@"model"] unsignedIntValue]==0x76697274&&[a[0][@"active"] boolValue]&&[a[0][@"main"] boolValue];
}
static bool retina(NSArray *a) {
    return fallback(a)&&[a[0][@"width"] unsignedIntValue]==1920&&[a[0][@"height"] unsignedIntValue]==1080&&
        [a[0][@"pixel_width"] unsignedIntValue]==3840&&[a[0][@"pixel_height"] unsignedIntValue]==2160&&[a[0][@"refresh"] doubleValue]==60;
}
static void report(NSString *phase,bool passed) {
    NSMutableArray *screens=[NSMutableArray new];for(NSScreen *s in NSScreen.screens)
        [screens addObject:@{@"id":s.deviceDescription[@"NSScreenNumber"],@"width":@(s.frame.size.width),@"height":@(s.frame.size.height),@"scale":@(s.backingScaleFactor)}];
    emit(@{@"phase":phase,@"passed":@(passed),@"displays":inventory()?:@[],@"screens":screens});
}
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired);alarm(45);[NSApplication sharedApplication];
    // --size WxH: like --configure, but the fallback adopts WxH HiDPI (e.g. a
    // remote client's own size) instead of 1920x1080. Not idempotent-checked.
    unsigned wantW=1920,wantH=1080;bool sized=false;
    if(argc==3&&!strcmp(argv[1],"--size")&&sscanf(argv[2],"%ux%u",&wantW,&wantH)==2&&wantW>=640&&wantH>=480&&wantW<=1920&&wantH<=1152)sized=true;
    else if(argc!=2||(strcmp(argv[1],"--configure")&&strcmp(argv[1],"--status")&&strcmp(argv[1],"--low-resolution")))return 2;
    NSArray *before=inventory();
    if(!strcmp(argv[1],"--status")){report(@"status",retina(before));return retina(before)?0:1;}
    if(!fallback(before)){emit(@{@"error":@"expected exactly one active headless fallback display; no changes made",@"displays":before?:@[]});return 2;}
    if(!strcmp(argv[1],"--low-resolution")) {
        bool ok=selectMode(1920,1080,1920,1080);pump(0.5);report(@"low-resolution",ok);return ok?0:3;
    }
    // Be idempotent: never switch an already-correct fallback mode.
    if(!sized&&retina(before)){report(@"configured",true);return 0;}
    if(!abi()){emit(@{@"error":@"virtual display ABI is unsupported; no changes made"});return 2;}
    CGVirtualDisplayDescriptor *d=[CGVirtualDisplayDescriptor new];
    d.queue=dispatch_get_main_queue();d.name=@"Raphael Retina setup";
    d.vendorID=0x5250;d.productID=0x344b;d.serialNum=0x344b0001;d.serialNumber=0x344b0001;
    d.maxPixelsWide=3840;d.maxPixelsHigh=2304;d.sizeInMillimeters=CGSizeMake(600,337.5);
    d.redPrimary=CGPointMake(0.64,0.33);d.greenPrimary=CGPointMake(0.30,0.60);
    d.bluePrimary=CGPointMake(0.15,0.06);d.whitePoint=CGPointMake(0.3127,0.3290);
    CGVirtualDisplay *display=[[CGVirtualDisplay alloc] initWithDescriptor:d];
    if(!display){emit(@{@"error":@"temporary virtual display refused"});return 3;}
    CGDirectDisplayID temporary=display.displayID;
    CGVirtualDisplayMode *mode=[[CGVirtualDisplayMode alloc] initWithWidth:wantW height:wantH refreshRate:60];
    CGVirtualDisplaySettings *settings=[CGVirtualDisplaySettings new];settings.hiDPI=1;settings.rotation=0;settings.modes=mode?@[mode]:@[];
    bool applied=mode&&[display applySettings:settings];
    // On24G830 the temporary display is online but lacks a public mode object.
    // Its chosen dimensions become the fallback default after removal. Verify
    // the fallback through public APIs; never treat applySettings as proof.
    pump(2);display=nil;
    bool removed=false;
    for(unsigned i=0;i<100&&!removed;i++) {
        pump(0.05);NSArray *a=inventory();removed=a!=nil;
        for(NSDictionary *row in a)if([row[@"id"] unsignedIntValue]==temporary)removed=false;
        removed=removed&&fallback(a);
    }
    // Removing the temporary60Hz display chooses the fallback default itself.
    // Do not issue a redundant CGDisplaySetDisplayMode on that synthetic mode.
    bool selected=applied&&removed;pump(0.5);
    NSArray *after=inventory();
    bool ok=selected&&(sized?(fallback(after)&&[after[0][@"width"] unsignedIntValue]==wantW&&[after[0][@"height"] unsignedIntValue]==wantH&&
                                 [after[0][@"pixel_width"] unsignedIntValue]==2*wantW):retina(after));
    // A mismatch is reported for supervised recovery, not followed by another
    // unqualified synthetic-mode switch.
    emit(@{@"phase":@"transition",@"applied":@(applied),@"temporary_removed":@(removed),@"selected":@(selected)});
    report(@"configured",ok);return ok?0:3;
}}
