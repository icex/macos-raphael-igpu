// Keep a CGVirtualDisplay online with a broad HiDPI mode table so remote clients
// (Apple Screen Sharing "client resolution", Sunshine) can switch the guest's
// screen to their own size. Private SPI is ABI-guarded like remote-retina.m.
// Usage: virtual-display-server --serve [--control-dir ABS] [--guest-scale 1|2]
// Legacy --modes values retain their historical 2x physical extents at either scale.
#import <CoreGraphics/CoreGraphics.h>
#import <AppKit/AppKit.h>
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <unistd.h>
#include "console-display-control.h"
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
static bool selectMode(CGDirectDisplayID did,unsigned w,unsigned h,unsigned scale) {
    CFArrayRef modes=CGDisplayCopyAllDisplayModes(did,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
    bool ok=false;
    if(modes)for(CFIndex i=0;i<CFArrayGetCount(modes)&&!ok;i++) {
        CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
        if(CGDisplayModeGetWidth(m)==w&&CGDisplayModeGetHeight(m)==h&&CGDisplayModeGetPixelWidth(m)==scale*w&&CGDisplayModeGetPixelHeight(m)==scale*h)
            ok=CGDisplaySetDisplayMode(did,m,NULL)==kCGErrorSuccess;
    }
    if(modes)CFRelease(modes);return ok;
}

static double controlNow(void) {struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+t.tv_nsec/1e9;}
static bool controlIdentity(CGDirectDisplayID did) {
 return CGDisplayIsOnline(did)&&CGDisplayVendorNumber(did)==0x5250&&CGDisplayModelNumber(did)==0x3453;
}
static bool controlTarget(CGDirectDisplayID did) {
 return controlIdentity(did)&&CGDisplayBounds(did).origin.x==0&&CGDisplayBounds(did).origin.y==0;
}
static CGDisplayModeRef controlMode(CGDirectDisplayID did,unsigned w,unsigned h,unsigned scale) {
 CFArrayRef all=CGDisplayCopyAllDisplayModes(did,(__bridge CFDictionaryRef)@{(id)kCGDisplayShowDuplicateLowResolutionModes:@YES});
 CGDisplayModeRef result=NULL;
 if(all)for(CFIndex i=0;i<CFArrayGetCount(all);i++){
  CGDisplayModeRef m=(CGDisplayModeRef)CFArrayGetValueAtIndex(all,i);
  if(CGDisplayModeGetPixelWidth(m)==w&&CGDisplayModeGetPixelHeight(m)==h&&CGDisplayModeGetWidth(m)*scale==w&&CGDisplayModeGetHeight(m)*scale==h){result=CGDisplayModeRetain(m);break;}
 }
 if(all)CFRelease(all);return result;
}
@interface RGDisplayControl : NSObject {
 int listener,peer,lockFD;double expires;
 uint8_t request[RG_CONTROL_REQUEST_MAX+1],reply[RG_CONTROL_REPLY];size_t received,sent;
 bool replying,waitingMode,waitingVerify,tableUncertain;unsigned requestFlags,guestScale;double stable;
 RGModes dynamicModes;
 CGDirectDisplayID originalID;
}
@property(strong) CGVirtualDisplay *display;
@property(strong) NSMutableArray *modes;
@property(copy) NSArray *baseModes;
@property(copy) NSString *socketPath;
- (BOOL)start:(NSString *)directory display:(CGVirtualDisplay *)display modes:(NSMutableArray *)modes scale:(unsigned)scale;
- (void)tick;
@end
@implementation RGDisplayControl
- (BOOL)start:(NSString *)directory display:(CGVirtualDisplay *)display modes:(NSMutableArray *)modes scale:(unsigned)scale {
 guestScale=scale;
 listener=peer=lockFD=-1;
 if(!directory.isAbsolutePath||![directory.stringByStandardizingPath isEqual:directory])return NO;
 // Validate every ancestor: never traverse a symbolic link or writable foreign directory.
 NSString *part=@"/";struct stat st;
 for(NSString *component in directory.pathComponents){
  if([component isEqual:@"/"])continue;part=[part stringByAppendingPathComponent:component];
  if(lstat(part.fileSystemRepresentation,&st)<0){
   if(![part isEqual:directory]||errno!=ENOENT||mkdir(part.fileSystemRepresentation,0700))return NO;
   if(lstat(part.fileSystemRepresentation,&st))return NO;
  }
  if(!S_ISDIR(st.st_mode)||(st.st_uid!=0&&st.st_uid!=getuid())||(st.st_mode&0022))return NO;
 }
 if(st.st_uid!=getuid()||(st.st_mode&0777)!=0700)return NO;
 NSString *lock=[directory stringByAppendingPathComponent:@"owner.lock"];
 lockFD=open(lock.fileSystemRepresentation,O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);
 if(lockFD<0||fstat(lockFD,&st)||!S_ISREG(st.st_mode)||st.st_uid!=getuid()||st.st_nlink!=1||(st.st_mode&0777)!=0600||flock(lockFD,LOCK_EX|LOCK_NB))return NO;
 self.socketPath=[directory stringByAppendingPathComponent:@"control.sock"];
 struct sockaddr_un addr={0};addr.sun_family=AF_UNIX;
 if(strlen(self.socketPath.fileSystemRepresentation)>=sizeof(addr.sun_path))return NO;
 strcpy(addr.sun_path,self.socketPath.fileSystemRepresentation);
 // The lifetime lock excludes another conforming holder. Reclaim only a
 // refused, same-owner socket with stable inode identity; never a live endpoint.
 if(lstat(addr.sun_path,&st)==0){
  if(!S_ISSOCK(st.st_mode)||st.st_uid!=getuid()||(st.st_mode&0777)!=0600)return NO;
  int probe=socket(AF_UNIX,SOCK_STREAM,0);if(probe<0)return NO;
  if(fcntl(probe,F_SETFL,O_NONBLOCK)){close(probe);return NO;}
  int connected=connect(probe,(struct sockaddr *)&addr,sizeof(addr));int saved=errno;close(probe);
  if(connected==0||saved!=ECONNREFUSED)return NO;
  struct stat again;if(lstat(addr.sun_path,&again)||again.st_dev!=st.st_dev||again.st_ino!=st.st_ino||!S_ISSOCK(again.st_mode)||again.st_uid!=getuid())return NO;
  if(unlink(addr.sun_path))return NO;
 }else if(errno!=ENOENT)return NO;
 listener=socket(AF_UNIX,SOCK_STREAM,0);if(listener<0)return NO;
 if(fcntl(listener,F_SETFL,O_NONBLOCK)||fcntl(listener,F_SETFD,FD_CLOEXEC))return NO;
 mode_t old=umask(077);int bound=bind(listener,(struct sockaddr *)&addr,sizeof(addr));umask(old);
 if(bound||chmod(addr.sun_path,0600)||listen(listener,1))return NO;
 self.display=display;self.modes=[modes mutableCopy];self.baseModes=[modes copy];originalID=display.displayID;
 return YES;
}
- (void)closePeer {if(peer>=0)close(peer);peer=-1;received=sent=0;replying=false;waitingMode=waitingVerify=false;requestFlags=0;stable=-1;}
- (void)respond {
 unsigned status=rg_validate(request,received),flags=requestFlags;
 if(!status&&rg_request_scale(request)!=guestScale)status=2;
 unsigned w=received>=20?rg_read32(request+12):0,h=received>=20?rg_read32(request+16):0;
 CGDisplayModeRef chosen=NULL;
 bool identity=self.display.displayID==originalID&&controlIdentity(originalID);
 if(!status&&(!identity||controlNow()>=expires-.25))status=4;
 if(!status&&!waitingMode&&!waitingVerify&&!controlTarget(originalID))status=4;
 if(!status&&waitingVerify){
  CGDisplayModeRef observed=CGDisplayCopyDisplayMode(originalID);
  bool ready=controlTarget(originalID)&&observed&&CGDisplayModeGetPixelWidth(observed)==w&&CGDisplayModeGetPixelHeight(observed)==h&&CGDisplayModeGetWidth(observed)*guestScale==w&&CGDisplayModeGetHeight(observed)*guestScale==h;
  if(observed)CFRelease(observed);
  int settled=rg_settle(&stable,identity,ready,controlNow()>=expires-.25,controlNow());
  if(!settled)return;
  if(settled<0)status=4;
 }

 if(!status&&!waitingVerify){
  chosen=controlMode(originalID,w,h,guestScale);
  if(waitingMode){
   int settled=rg_settle(&stable,identity,chosen&&controlTarget(originalID),controlNow()>=expires-.25,controlNow());
   if(settled<=0){if(chosen)CGDisplayModeRelease(chosen);chosen=NULL;if(!settled)return;status=4;}
   else {waitingMode=false;stable=-1;}
  }
  if(!status&&!chosen){
   if(tableUncertain)status=3;
   else {
    // Preserve the actual active geometry, not the last requested geometry.
    CGDisplayModeRef before=CGDisplayCopyDisplayMode(originalID);
    RGGeometry current={before?(uint32_t)CGDisplayModeGetPixelWidth(before):0,before?(uint32_t)CGDisplayModeGetPixelHeight(before):0};
    if(before)CFRelease(before);
    RGModes candidatePolicy=dynamicModes;
    if(!current.w||!current.h||!controlTarget(originalID))status=4;
    else if(!rg_insert(&candidatePolicy,(RGGeometry){w,h},current))status=5;
    else {
     NSMutableArray *candidate=[self.baseModes mutableCopy];
     for(unsigned i=0;i<candidatePolicy.count;i++){
      RGGeometry g=candidatePolicy.items[i];
      [candidate addObject:[[CGVirtualDisplayMode alloc] initWithWidth:g.w/guestScale height:g.h/guestScale refreshRate:60]];
     }
     CGVirtualDisplaySettings *settings=[CGVirtualDisplaySettings new];settings.hiDPI=(guestScale==2);settings.rotation=0;settings.modes=candidate;
     if(![self.display applySettings:settings]){
      // A false SPI return does not prove that no state changed. Restore the
      // retained table on the same object; never pretend the request succeeded.
      settings.modes=self.modes;
      bool restored=self.display.displayID==originalID&&controlTarget(originalID)&&[self.display applySettings:settings];
      tableUncertain=!restored;status=3;
      emit(@{@"phase":@"control-table-restore",@"restored":@(restored)});
     }else {
      self.modes=candidate;dynamicModes=candidatePolicy;requestFlags=flags|2;waitingMode=true;stable=-1;
      emit(@{@"phase":@"control-table-wait",@"display":@(originalID),@"pixel_width":@(w),@"pixel_height":@(h)});return;
     }
    }
   }
  }
 }
 if(!status&&(self.display.displayID!=originalID||!controlTarget(originalID)))status=4;
 if(!status&&!waitingVerify){
  CGDisplayModeRef current=CGDisplayCopyDisplayMode(originalID);
  bool same=current&&CGDisplayModeGetIODisplayModeID(current)==CGDisplayModeGetIODisplayModeID(chosen)&&CGDisplayModeGetPixelWidth(current)==w&&CGDisplayModeGetPixelHeight(current)==h;
  if(current)CFRelease(current);
  if(!same){
   CGDisplayConfigRef config=NULL;CGError e=CGBeginDisplayConfiguration(&config);
   if(!e){e=CGConfigureDisplayWithDisplayMode(config,originalID,chosen,NULL);if(!e)e=CGCompleteDisplayConfiguration(config,kCGConfigureForSession);else CGCancelDisplayConfiguration(config);}
   if(e)status=3;else flags|=1;
  }
  if(!status){
   requestFlags=flags;waitingVerify=true;stable=-1;
   emit(@{@"phase":@"control-verify-wait",@"display":@(originalID),@"pixel_width":@(w),@"pixel_height":@(h)});
   if(chosen)CGDisplayModeRelease(chosen);
   return;
  }
 }
 CGDisplayModeRef actual=CGDisplayCopyDisplayMode(originalID);
 if(!status&&(!actual||self.display.displayID!=originalID||!controlTarget(originalID)||CGDisplayModeGetPixelWidth(actual)!=w||CGDisplayModeGetPixelHeight(actual)!=h||CGDisplayModeGetWidth(actual)*guestScale!=w||CGDisplayModeGetHeight(actual)*guestScale!=h))status=4;
 if(!status)rg_touch(&dynamicModes,(RGGeometry){w,h});
 uint32_t values[10]={RG_CONTROL_MAGIC,received>=8?rg_read32(request+4):0,received>=12?rg_read32(request+8):0,status,originalID,
  actual?(uint32_t)CGDisplayModeGetPixelWidth(actual):0,actual?(uint32_t)CGDisplayModeGetPixelHeight(actual):0,
  actual?(uint32_t)CGDisplayModeGetWidth(actual):0,actual?(uint32_t)CGDisplayModeGetHeight(actual):0,flags};
 for(unsigned i=0;i<10;i++)rg_write32(reply+4*i,values[i]);
 if(actual)CFRelease(actual);if(chosen)CFRelease(chosen);replying=true;
 emit(@{@"phase":@"control-result",@"sequence":@(values[2]),@"status":@(status),@"display":@(originalID),@"pixel_width":@(values[5]),@"pixel_height":@(values[6]),@"flags":@(flags)});
}
- (void)tick { @autoreleasepool {
 if(peer<0){
  peer=accept(listener,NULL,NULL);if(peer<0)return;
  uid_t uid;gid_t gid;int yes=1;
  if(getpeereid(peer,&uid,&gid)||uid!=getuid()||fcntl(peer,F_SETFL,O_NONBLOCK)||fcntl(peer,F_SETFD,FD_CLOEXEC)||setsockopt(peer,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof(yes))){[self closePeer];return;}
  expires=controlNow()+4.75;received=sent=0;replying=false;waitingMode=waitingVerify=false;requestFlags=0;stable=-1;
 }
 if(controlNow()>=expires){[self closePeer];return;}
 if((waitingMode||waitingVerify)&&!replying)[self respond];
 if(!replying&&!waitingMode&&!waitingVerify){
  ssize_t n=read(peer,request+received,sizeof(request)-received);
  if(n<0){if(errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINTR)[self closePeer];return;}
  received+=(size_t)n;
  int frame=rg_request_frame(request,received,n==0);
  if(frame<0){[self closePeer];return;}
  if(frame>0)[self respond];
 }
 if(replying){
  ssize_t n=write(peer,reply+sent,sizeof(reply)-sent);
  if(n<0){if(errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINTR)[self closePeer];return;}
  sent+=(size_t)n;if(sent==sizeof(reply))[self closePeer];
 }
}}
@end
int main(int argc,const char **argv) { @autoreleasepool {
    [NSApplication sharedApplication];
    if(argc<2)return 2;
    if(!strcmp(argv[1],"--abi")){emit(@{@"abi":@(abi())});return abi()?0:1;}
    if(strcmp(argv[1],"--serve"))return 2;
    if(!abi()){emit(@{@"error":@"virtual display ABI is unsupported"});return 2;}
    NSMutableArray *modes=[NSMutableArray new];NSMutableArray *names=[NSMutableArray new];
    unsigned guestScale=2;bool scaleSeen=false;
    NSString *controlDir=nil,*customModes=nil;
    for(int i=2;i<argc;i+=2){
        if(i+1>=argc)return 2;
        if(!strcmp(argv[i],"--control-dir")&&!controlDir)controlDir=@(argv[i+1]);
        else if(!strcmp(argv[i],"--modes")&&!customModes)customModes=@(argv[i+1]);
        else if(!strcmp(argv[i],"--guest-scale")&&!scaleSeen){
            if(strcmp(argv[i+1],"1")&&strcmp(argv[i+1],"2"))return 2;
            guestScale=(unsigned)(argv[i+1][0]-'0');scaleSeen=true;
        }else return 2;
    }
    if(customModes&&controlDir)return 2;
    unsigned initialW=3840/guestScale,initialH=2160/guestScale;
    if(customModes) {
        for(NSString *item in [customModes componentsSeparatedByString:@","]) {
            NSArray *wh=[item componentsSeparatedByString:@"x"];if(wh.count!=2)continue;
            unsigned w=(unsigned)[wh[0] intValue],h=(unsigned)[wh[1] intValue];
            if(w<640||h<480||w>1920||h>1152)continue;
            [modes addObject:[[CGVirtualDisplayMode alloc] initWithWidth:w*2/guestScale height:h*2/guestScale refreshRate:60]];[names addObject:[NSString stringWithFormat:@"%ux%u",w*2/guestScale,h*2/guestScale]];
        }
    } else for(size_t i=0;i<sizeof(kDefaultModes)/sizeof(kDefaultModes[0]);i++) {
        [modes addObject:[[CGVirtualDisplayMode alloc] initWithWidth:kDefaultModes[i][0]*2/guestScale height:kDefaultModes[i][1]*2/guestScale refreshRate:60]];
        [names addObject:[NSString stringWithFormat:@"%ux%u",kDefaultModes[i][0]*2/guestScale,kDefaultModes[i][1]*2/guestScale]];
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
    CGVirtualDisplaySettings *settings=[CGVirtualDisplaySettings new];settings.hiDPI=(guestScale==2);settings.rotation=0;settings.modes=modes;
    bool applied=[display applySettings:settings];
    NSDate *until=[NSDate dateWithTimeIntervalSinceNow:2];
    while(until.timeIntervalSinceNow>0)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.05]];
    bool selected=applied&&selectMode(display.displayID,initialW,initialH,guestScale);
    emit(@{@"phase":@"serving",@"applied":@(applied),@"display":@(display.displayID),@"initial_selected":@(selected),@"guest_scale":@(guestScale),
           @"modes":names,@"displays":inventory()});
    RGDisplayControl *control=nil;
    if(controlDir){
        control=[RGDisplayControl new];
        if(![control start:controlDir display:display modes:modes scale:guestScale]){emit(@{@"error":@"control endpoint refused"});return 4;}
        [NSTimer scheduledTimerWithTimeInterval:0.02 repeats:YES block:^(NSTimer *timer){(void)timer;[control tick];}];
        emit(@{@"phase":@"control-ready",@"display":@(display.displayID),@"socket":control.socketPath,@"guest_scale":@(guestScale)});
    }
    signal(SIGTERM,exit);
    [[NSRunLoop currentRunLoop] run];   // hold the display until killed
    return 0;
}}
