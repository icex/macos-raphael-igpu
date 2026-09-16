// Bounded, reversible feasibility check; CGVirtualDisplay is private SPI.
#import <CoreGraphics/CoreGraphics.h>
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

static volatile sig_atomic_t stopping=0;
static void stop(int s) {(void)s;stopping=1;}
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
        CGDisplayModeRef m=CGDisplayCopyDisplayMode(ids[i]);if(!m)return nil;
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
    if(!s||strcmp(s.methodReturnType,result)||s.numberOfArguments!=args.count+2)return false;
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
        signature(@"CGVirtualDisplayMode",@"initWithWidth:height:refreshRate:",@"@",@[@(@encode(unsigned int)),@(@encode(unsigned int)),@(@encode(double))]) &&
        signature(@"CGVirtualDisplay",@"initWithDescriptor:",@"@",@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"applySettings:",@encode(BOOL),@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"displayID",@encode(unsigned int),@[]) &&
        signature(@"CGVirtualDisplaySettings",@"setModes:",@encode(void),@[@"@"]);
}
int main(int argc,const char **argv) { @autoreleasepool {
    if(argc!=2||(strcmp(argv[1],"0")&&strcmp(argv[1],"1")))return 2;
    signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGALRM,expired);alarm(110);
    bool hidpi=atoi(argv[1]);NSArray *before=inventory();bool abiValid=abi();
    emit(@{@"phase":@"before",@"displays":before?:@[],@"abi_valid":@(abiValid),@"hidpi":@(hidpi),@"pid":@(getpid())});
    // Do not change a physical monitor's topology. This targets the known headless fallback only.
    if(!abiValid||before.count!=1||![before[0][@"active"] boolValue]||![before[0][@"main"] boolValue]||[before[0][@"model"] unsignedIntValue]!=0x76697274)return 2;
    CGVirtualDisplayDescriptor *d=[CGVirtualDisplayDescriptor new];
    d.queue=dispatch_get_main_queue();d.name=@"Raphael 4K feasibility";
    d.vendorID=0x5250;d.productID=0x344b;d.serialNum=0x344b0001;d.serialNumber=0x344b0001;
    d.maxPixelsWide=3840;d.maxPixelsHigh=2160;d.sizeInMillimeters=CGSizeMake(600,337.5);
    d.redPrimary=CGPointMake(0.64,0.33);d.greenPrimary=CGPointMake(0.30,0.60);
    d.bluePrimary=CGPointMake(0.15,0.06);d.whitePoint=CGPointMake(0.3127,0.3290);
    CGVirtualDisplay *display=[[CGVirtualDisplay alloc] initWithDescriptor:d];
    if(!display){emit(@{@"phase":@"error",@"error":@"display creation refused"});return 3;}
    CGDirectDisplayID target=display.displayID;
    CGVirtualDisplaySettings *settings=[CGVirtualDisplaySettings new];settings.hiDPI=hidpi;settings.rotation=0;
    CGVirtualDisplayMode *mode=[[CGVirtualDisplayMode alloc] initWithWidth:hidpi?1920:3840 height:hidpi?1080:2160 refreshRate:60];
    settings.modes=mode?@[mode]:@[];bool applied=mode&&[display applySettings:settings];
    bool matched=false;
    for(unsigned i=0;i<50&&!stopping&&!matched;i++) {
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        for(NSDictionary *row in inventory())if([row[@"id"] unsignedIntValue]==target)
            matched=[row[@"active"] boolValue]&&[row[@"pixel_width"] unsignedIntValue]==3840&&
                [row[@"pixel_height"] unsignedIntValue]==2160&&[row[@"width"] unsignedIntValue]==(hidpi?1920:3840)&&
                [row[@"height"] unsignedIntValue]==(hidpi?1080:2160);
    }
    emit(@{@"phase":@"ready",@"applied":@(applied),@"matched":@(matched),@"target":@(target),@"displays":inventory()?:@[],@"hold_seconds":@60});
    NSDate *until=[NSDate dateWithTimeIntervalSinceNow:60];
    while(applied&&matched&&!stopping&&until.timeIntervalSinceNow>0)
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
    display=nil;
    bool removed=false;
    for(unsigned i=0;i<50&&!removed;i++) {
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        NSArray *current=inventory();removed=current!=nil;
        for(NSDictionary *row in current)if([row[@"id"] unsignedIntValue]==target)removed=false;
    }
    NSArray *after=inventory();bool fallback=after.count==1&&[after[0][@"model"] unsignedIntValue]==0x76697274;
    emit(@{@"phase":@"done",@"removed":@(removed),@"fallback_restored":@(fallback),@"displays":after?:@[],@"passed":@(applied&&matched&&removed&&fallback)});
    return applied&&matched&&removed&&fallback?0:4;
}}
