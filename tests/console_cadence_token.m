// Visible AppKit draw IDs, not GPU presentation timestamps. No display mode change.
#import <AppKit/AppKit.h>
#include <stdint.h>
#include <ctype.h>
#include <string.h>
#include <stdlib.h>
#include <signal.h>
#include <unistd.h>
static uint8_t nonce[8];
static uint32_t crc32bytes(const uint8_t *p,int n){uint32_t c=~0u;for(int i=0;i<n;i++){c^=p[i];for(int b=0;b<8;b++)c=(c>>1)^(0xedb88320u&-(c&1));}return ~c;}
static void expired(int s){(void)s;_exit(124);}
@interface TokenView:NSView
@property uint32_t sequence;
@end
@implementation TokenView
-(BOOL)isFlipped{return YES;}
-(void)drawRect:(NSRect)dirty{(void)dirty;
 [[NSColor colorWithCalibratedWhite:.12 alpha:1]setFill];NSRectFill(self.bounds);
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
int main(int argc,const char **argv){@autoreleasepool{
 if(argc!=3||strlen(argv[1])!=16)return 2;
 for(int i=0;i<16;i++)if(!isxdigit((unsigned char)argv[1][i]))return 2;
 for(int i=0;i<8;i++){char pair[]={argv[1][i*2],argv[1][i*2+1],0};nonce[i]=(uint8_t)strtoul(pair,NULL,16);}
 char *end=NULL;long seconds=strtol(argv[2],&end,10);if(*end||seconds<1||seconds>120)return 2;
 signal(SIGALRM,expired);alarm((unsigned)seconds+10);
 [NSApplication sharedApplication];[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
 NSScreen *screen=NSScreen.mainScreen;if(!screen)return 3;
 NSWindow *window=[[NSWindow alloc]initWithContentRect:screen.frame styleMask:NSWindowStyleMaskBorderless backing:NSBackingStoreBuffered defer:NO];
 window.level=NSFloatingWindowLevel;window.title=@"Raphael visible cadence token";
 TokenView *view=[[TokenView alloc]initWithFrame:NSMakeRect(0,0,screen.frame.size.width,screen.frame.size.height)];window.contentView=view;
 [window makeKeyAndOrderFront:nil];[NSApp activateIgnoringOtherApps:YES];
 printf("TOKEN nonce=%s duration=%ld logical=%.0fx%.0f scale=%.1f\n",argv[1],seconds,screen.frame.size.width,screen.frame.size.height,screen.backingScaleFactor);fflush(stdout);
 NSTimer *tick=[NSTimer scheduledTimerWithTimeInterval:1.0/60 repeats:YES block:^(NSTimer*t){(void)t;[view setNeedsDisplay:YES];}];
 double until=NSProcessInfo.processInfo.systemUptime+seconds;
 while(NSProcessInfo.processInfo.systemUptime<until){@autoreleasepool{
  NSEvent *event=[NSApp nextEventMatchingMask:NSEventMaskAny untilDate:[NSDate dateWithTimeIntervalSinceNow:.01] inMode:NSDefaultRunLoopMode dequeue:YES];if(event)[NSApp sendEvent:event];[NSApp updateWindows];
 }}
 [tick invalidate];[window orderOut:nil];printf("TOKEN_DONE draws=%u\n",view.sequence);fflush(stdout);alarm(0);return 0;
}}
