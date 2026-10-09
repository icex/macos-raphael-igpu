// Source-cadence A/B: DRAW means drawRect calls returned, never scanout/presentation.
// clang -O2 -fobjc-arc -fblocks ... -framework AppKit -framework CoreVideo
#import <AppKit/AppKit.h>
#import <CoreVideo/CoreVideo.h>
#import <dispatch/dispatch.h>
#include "console_cadence_band.h"
#include <stdint.h>
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>
static uint8_t nonce[8];
static BOOL paced=NO;
static CGImageRef *bands=NULL;
static uint32_t bandCount=0;
static int pending=0;
static uint64_t requests=0,coalesced=0;
static void released(void *info,const void *data,size_t size){(void)info;(void)size;free((void *)data);}
static BOOL prepareBands(unsigned seconds){
 bandCount=seconds*120+16;bands=calloc(bandCount,sizeof(*bands));if(!bands)return NO;
 CGColorSpaceRef color=CGColorSpaceCreateDeviceRGB();if(!color)return NO;
 for(uint32_t i=0;i<bandCount;i++){
  uint8_t *pixels=malloc(RGPU_BAND_BYTES);if(!pixels){CGColorSpaceRelease(color);return NO;}
  rgpu_band(pixels,nonce,i+1);
  CGDataProviderRef provider=CGDataProviderCreateWithData(NULL,pixels,RGPU_BAND_BYTES,released);
  if(!provider){free(pixels);CGColorSpaceRelease(color);return NO;}
  bands[i]=CGImageCreate(RGPU_BAND_W,RGPU_BAND_H,8,32,RGPU_BAND_W*4,color,
     kCGBitmapByteOrder32Big|kCGImageAlphaPremultipliedLast,provider,NULL,false,kCGRenderingIntentDefault);
  CGDataProviderRelease(provider);if(!bands[i]){CGColorSpaceRelease(color);return NO;}
 }
 CGColorSpaceRelease(color);return YES;
}
static uint32_t crc32bytes(const uint8_t *p,int n){uint32_t c=~0u;for(int i=0;i<n;i++){c^=p[i];for(int b=0;b<8;b++)c=(c>>1)^(0xedb88320u&-(c&1));}return ~c;}
static void expired(int s){(void)s;_exit(124);}
@interface TokenView:NSView
@property uint32_t sequence;
@end
@implementation TokenView
-(BOOL)isFlipped{return YES;}
-(void)drawRect:(NSRect)dirty{(void)dirty;
 [[NSColor colorWithCalibratedWhite:.12 alpha:1]setFill];NSRectFill(self.bounds);
 if(paced){
  uint32_t seq=self.sequence+1;if(seq>bandCount){fprintf(stderr,"token pool exhausted\n");exit(6);}
  CGContextRef context=NSGraphicsContext.currentContext.CGContext;
  CGContextSaveGState(context);CGContextSetInterpolationQuality(context,kCGInterpolationNone);
  // Quartz images are bottom-up in this flipped AppKit view.
  CGContextTranslateCTM(context,16,64+96);CGContextScaleCTM(context,8,-8);
  CGContextDrawImage(context,CGRectMake(0,0,RGPU_BAND_W,RGPU_BAND_H),bands[seq-1]);
  CGContextRestoreGState(context);self.sequence=seq;
  printf("DRAW %u %.9f\n",seq,NSProcessInfo.processInfo.systemUptime);fflush(stdout);return;
 }
 uint8_t data[20]={'R','G','P','T'};memcpy(data+4,nonce,8);uint32_t seq=++self.sequence;
 for(int i=0;i<4;i++)data[12+i]=(seq>>(24-i*8))&255;
 uint32_t crc=crc32bytes(data,16);for(int i=0;i<4;i++)data[16+i]=(crc>>(24-i*8))&255;
 for(int copy=0;copy<2;copy++){
  int left=16+160*copy,top=64,cell=8;
  [[NSColor magentaColor]setFill];NSRectFill(NSMakeRect(left,top,18*cell,12*cell));
  for(int bit=0;bit<160;bit++){
   [((data[bit/8]>>(7-bit%8))&1 ? [NSColor whiteColor]:[NSColor blackColor])setFill];
   NSRectFill(NSMakeRect(left+(1+bit%16)*cell,top+(1+bit/16)*cell,cell,cell));
  }
 }
 printf("DRAW %u %.9f\n",seq,NSProcessInfo.processInfo.systemUptime);fflush(stdout);
}
@end
static CVReturn tickLink(CVDisplayLinkRef link,const CVTimeStamp *a,const CVTimeStamp *b,
 CVOptionFlags c,CVOptionFlags *d,void *context){
 (void)link;(void)a;(void)b;(void)c;(void)d;
 __atomic_fetch_add(&requests,1,__ATOMIC_RELAXED);
 if(__atomic_exchange_n(&pending,1,__ATOMIC_ACQ_REL)){__atomic_fetch_add(&coalesced,1,__ATOMIC_RELAXED);return kCVReturnSuccess;}
 TokenView *view=(__bridge TokenView *)context;
 dispatch_async(dispatch_get_main_queue(),^{__atomic_store_n(&pending,0,__ATOMIC_RELEASE);[view setNeedsDisplay:YES];});
 return kCVReturnSuccess;
}
int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=4||strlen(argv[1])!=16)return 2;
 if(strcmp(argv[3],"baseline")&&strcmp(argv[3],"prerendered"))return 2;
 paced=!strcmp(argv[3],"prerendered");
 for(int i=0;i<16;i++)if(!isxdigit((unsigned char)argv[1][i]))return 2;
 for(int i=0;i<8;i++){char pair[]={argv[1][i*2],argv[1][i*2+1],0};nonce[i]=(uint8_t)strtoul(pair,NULL,16);}
 char *end=NULL;long seconds=strtol(argv[2],&end,10);if(*end||seconds<1||seconds>120)return 2;
 signal(SIGALRM,expired);alarm((unsigned)seconds+10);
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
 NSScreen *screen=NSScreen.mainScreen;if(!screen)return 3;
 if(paced&&!prepareBands((unsigned)seconds))return 4;
 NSWindow *window=[[NSWindow alloc]initWithContentRect:screen.frame styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
 window.level=NSFloatingWindowLevel;window.title=@"Raphael visible cadence token";
 TokenView *view=[[TokenView alloc]initWithFrame:NSMakeRect(0,0,screen.frame.size.width,screen.frame.size.height)];window.contentView=view;
 [window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
 printf("TOKEN nonce=%s duration=%ld logical=%.0fx%.0f scale=%.1f\n",argv[1],seconds,screen.frame.size.width,screen.frame.size.height,screen.backingScaleFactor);fflush(stdout);
 printf("SOURCE_MODE %s scope=drawRect-return-not-presentation band_bytes=%lu\n",argv[3],(unsigned long)bandCount*RGPU_BAND_BYTES);fflush(stdout);
 NSTimer *tick=nil;CVDisplayLinkRef link=NULL;
 if(paced){
  CGDirectDisplayID display=[screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue];
  if(CVDisplayLinkCreateWithCGDisplay(display,&link)!=kCVReturnSuccess||
     CVDisplayLinkSetOutputCallback(link,tickLink,(__bridge void *)view)!=kCVReturnSuccess||
     CVDisplayLinkStart(link)!=kCVReturnSuccess)return 5;
  CVTime nominal=CVDisplayLinkGetNominalOutputVideoRefreshPeriod(link);
  printf("DISPLAY_LINK display=%u nominal_value=%lld nominal_scale=%d flags=%lld\n",display,
     (long long)nominal.timeValue,nominal.timeScale,(long long)nominal.flags);fflush(stdout);
 }else tick=[NSTimer scheduledTimerWithTimeInterval:1.0/60 repeats:YES block:^(NSTimer*t){(void)t;[view setNeedsDisplay:YES];}];
 double until=NSProcessInfo.processInfo.systemUptime+seconds;
 while(NSProcessInfo.processInfo.systemUptime<until){@autoreleasepool{
  NSEvent *event=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate dateWithTimeIntervalSinceNow:.01] inMode:NSDefaultRunLoopMode dequeue:YES];if(event)[NSApp sendEvent:event];[NSApp updateWindows];
 }}
 [tick invalidate];if(link){CVDisplayLinkStop(link);CVDisplayLinkRelease(link);}
 [window orderOut:nil];printf("TOKEN_DONE draws=%u\n",view.sequence);printf("SOURCE_DONE requests=%llu coalesced=%llu scope=requests-not-frames\n",(unsigned long long)__atomic_load_n(&requests,__ATOMIC_RELAXED),(unsigned long long)__atomic_load_n(&coalesced,__ATOMIC_RELAXED));fflush(stdout);alarm(0);return 0;
}}
