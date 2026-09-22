// Keep a CGVirtualDisplay online with a broad HiDPI mode table so remote clients
// (Apple Screen Sharing "client resolution", Sunshine) can switch the guest's
// screen to their own size. Private SPI is ABI-guarded like remote-retina.m.
// Usage: virtual-display-server --serve [--modes WxH,WxH,...] | --abi
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width height:(unsigned int)height refreshRate:(double)refreshRate;
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

// Logical (point) sizes; hiDPI doubles the backing. Covers iPads, MacBooks,
// common monitors and TVs at or below a 3840x2304 backing.
static const unsigned kDefaultModes[][2] = {
    {1024,768},{1080,810},{1112,834},{1180,820},{1194,834},{1210,840},{1280,720},{1280,800},
    {1280,1024},{1366,768},{1366,1024},{1376,1032},{1440,900},{1470,956},{1512,982},{1536,960},
    {1600,900},{1680,1050},{1728,1117},{1920,1080},{1920,1152}};

static void emit(NSDictionary *d) {
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes,1,j.length,stdout);putchar('\n');fflush(stdout);
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
        signature(@"CGVirtualDisplayMode",@"initWithWidth:height:refreshRate:","@",@[@(@encode(unsigned int)),@(@encode(unsigned int)),@(@encode(double))]) &&
        signature(@"CGVirtualDisplay",@"initWithDescriptor:","@",@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"applySettings:",@encode(BOOL),@[@"@"]) &&
        signature(@"CGVirtualDisplay",@"displayID",@encode(unsigned int),@[]) &&
        signature(@"CGVirtualDisplaySettings",@"setModes:",@encode(void),@[@"@"]);
}
static NSArray *inventory(void) {
    CGDirectDisplayID ids[32];uint32_t n=0;NSMutableArray *a=[NSMutableArray new];
    if(CGGetOnlineDisplayList(32,ids,&n)!=kCGErrorSuccess)return a;
    for(unsigned i=0;i<n;i++) {
        CGDisplayModeRef m=CGDisplayCopyDisplayMode(ids[i]);
        NSMutableDictionary *row=[@{@"id":@(ids[i]),@"main":@(CGDisplayIsMain(ids[i])!=0),@"active":@(CGDisplayIsActive(ids[i])!=0),
            @"model":@(CGDisplayModelNumber(ids[i]))} mutableCopy];
        if(m){row[@"width"]=@(CGDisplayModeGetWidth(m));row[@"height"]=@(CGDisplayModeGetHeight(m));
              row[@"pixel_width"]=@(CGDisplayModeGetPixelWidth(m));row[@"pixel_height"]=@(CGDisplayModeGetPixelHeight(m));CFRelease(m);}
        [a addObject:row];
    }
    return a;
}
static bool selectMode(CGDirectDisplayID did,unsigned w,unsigned h) {
    CFArrayRef modes=CGDisplayCopyAllDisplayModes(did,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
    bool ok=false;
    if(modes)for(CFIndex i=0;i<CFArrayGetCount(modes)&&!ok;i++) {
        CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
        if(CGDisplayModeGetWidth(m)==w&&CGDisplayModeGetHeight(m)==h&&CGDisplayModeGetPixelWidth(m)==2*w)
            ok=CGDisplaySetDisplayMode(did,m,NULL)==kCGErrorSuccess;
    }
    if(modes)CFRelease(modes);return ok;
}
int main(int argc,const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    if(argc<2)return 2;
    if(!strcmp(argv[1],"--abi")){emit(@{@"abi":@(abi())});return abi()?0:1;}
    if(strcmp(argv[1],"--serve"))return 2;
    if(!abi()){emit(@{@"error":@"virtual display ABI is unsupported"});return 2;}
    NSMutableArray *modes=[NSMutableArray new];NSMutableArray *names=[NSMutableArray new];
    unsigned initialW=1920,initialH=1080;
    if(argc>=4&&!strcmp(argv[2],"--modes")) {
        for(NSString *item in [@(argv[3]) componentsSeparatedByString:@","]) {
            NSArray *wh=[item componentsSeparatedByString:@"x"];if(wh.count!=2)continue;
            unsigned w=(unsigned)[wh[0] intValue],h=(unsigned)[wh[1] intValue];
            if(w<640||h<480||w>1920||h>1152)continue;
            [modes addObject:[[CGVirtualDisplayMode alloc] initWithWidth:w height:h refreshRate:60]];[names addObject:item];
        }
    } else for(size_t i=0;i<sizeof(kDefaultModes)/sizeof(kDefaultModes[0]);i++) {
        [modes addObject:[[CGVirtualDisplayMode alloc] initWithWidth:kDefaultModes[i][0] height:kDefaultModes[i][1] refreshRate:60]];
        [names addObject:[NSString stringWithFormat:@"%ux%u",kDefaultModes[i][0],kDefaultModes[i][1]]];
    }
    if(!modes.count){emit(@{@"error":@"no valid modes"});return 2;}
    CGVirtualDisplayDescriptor *d=[CGVirtualDisplayDescriptor new];
    d.queue=dispatch_get_main_queue();d.name=@"Raphael Virtual Display";
    d.vendorID=0x5250;d.productID=0x3453;d.serialNum=0x34530001;d.serialNumber=0x34530001;
    d.maxPixelsWide=3840;d.maxPixelsHigh=2304;d.sizeInMillimeters=CGSizeMake(600,337.5);
    d.redPrimary=CGPointMake(0.64,0.33);d.greenPrimary=CGPointMake(0.30,0.60);
    d.bluePrimary=CGPointMake(0.15,0.06);d.whitePoint=CGPointMake(0.3127,0.3290);
    d.terminationHandler=^{emit(@{@"phase":@"terminated"});exit(3);};
    CGVirtualDisplay *display=[[CGVirtualDisplay alloc] initWithDescriptor:d];
    if(!display){emit(@{@"error":@"virtual display refused"});return 3;}
    CGVirtualDisplaySettings *settings=[CGVirtualDisplaySettings new];settings.hiDPI=1;settings.rotation=0;settings.modes=modes;
    bool applied=[display applySettings:settings];
    NSDate *until=[NSDate dateWithTimeIntervalSinceNow:2];
    while(until.timeIntervalSinceNow>0)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    bool selected=applied&&selectMode(display.displayID,initialW,initialH);
    emit(@{@"phase":@"serving",@"applied":@(applied),@"display":@(display.displayID),@"initial_selected":@(selected),
           @"modes":names,@"displays":inventory()});
    signal(SIGTERM,exit);
    [[NSRunLoop currentRunLoop] run];   // hold the display until killed
    return 0;
}}
