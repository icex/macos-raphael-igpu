#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
int main(void) { @autoreleasepool {
 CGDirectDisplayID ids[16];uint32_t count=0;CGGetOnlineDisplayList(16,ids,&count);
 CGDirectDisplayID target=0;
 for(unsigned i=0;i<count;i++)if(CGDisplayVendorNumber(ids[i])==0x5250 && CGDisplayModelNumber(ids[i])==0x3453){if(target)return 2;target=ids[i];}
 if(!target)return 2;
 CGDisplayConfigRef c=NULL;CGError e=CGBeginDisplayConfiguration(&c);if(e)return 3;
 e=CGConfigureDisplayOrigin(c,target,0,0);
 for(unsigned i=0;i<count&&!e;i++)if(ids[i]!=target)e=CGConfigureDisplayMirrorOfDisplay(c,ids[i],target);
 if(e){CGCancelDisplayConfiguration(c);printf("configure error=%d\n",e);return 4;}
 e=CGCompleteDisplayConfiguration(c,kCGConfigureForSession);
 printf("layout error=%d target=%u main=%u\n",e,target,CGMainDisplayID());
 for(unsigned i=0;i<count;i++){CGRect r=CGDisplayBounds(ids[i]);printf("id=%u active=%d mirror=%u bounds=%.0f,%.0f %.0fx%.0f\n",ids[i],CGDisplayIsActive(ids[i]),CGDisplayMirrorsDisplay(ids[i]),r.origin.x,r.origin.y,r.size.width,r.size.height);}
 return e?5:0;
}}
