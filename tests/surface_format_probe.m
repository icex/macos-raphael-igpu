#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurface.h>
#include <math.h>
#include <signal.h>
#include <unistd.h>
static void deadline(int unused) { (void)unused; const char m[]="{\"phase\":\"deadline\"}\n"; write(1,m,sizeof(m)-1); _exit(124); }
static void emit(NSDictionary *d) { NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil]; fwrite(j.bytes,1,j.length,stdout); putchar('\n'); fflush(stdout); }
static float halfValue(uint16_t v) { unsigned e=(v>>10)&31,m=v&1023; return (v&32768?-1:1)*(e ? ldexpf(1+m/1024.f,(int)e-15):ldexpf(m/1024.f,-14)); }
int main(int argc,const char **argv) { @autoreleasepool {
 signal(SIGALRM,deadline); alarm(150);
 uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;
 id<MTLDevice> dev=nil; for(id<MTLDevice> d in MTLCopyAllDevices()) if(d.registryID==wanted) dev=d;
 if(!dev) {emit(@{@"error":@"exact registry device missing"});return 2;}
 NSError *err=nil;
 NSString *src=@"#include <metal_stdlib>\nusing namespace metal;\nstruct V {float4 p [[position]];};\nvertex V v(uint i [[vertex_id]]) {float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};return {float4(p[i],0,1)};}\nfragment float4 f(V in [[stage_in]],constant uint &layer [[buffer(0)]]) {uint2 p=uint2(in.p.xy);bool c=((p.x/13+p.y/11)%2)!=0; if(layer) return c?float4(.125,.0625,.375,.5):float4(.375,.125,.0625,.5);return float4(.125,.25,.5,1);}\n";
 id<MTLLibrary> lib=[dev newLibraryWithSource:src options:nil error:&err]; if(!lib){emit(@{@"error":err.description});return 2;}
 id<MTLCommandQueue> queue=[dev newCommandQueue];unsigned failures=0,cases=0;
 MTLPixelFormat formats[]={MTLPixelFormatBGRA8Unorm,MTLPixelFormatRGBA8Unorm,MTLPixelFormatRGBA16Float,MTLPixelFormatRGB10A2Unorm};
 for(unsigned fi=0;fi<4;fi++) for(unsigned mode=0;mode<3;mode++) {
 @autoreleasepool {
 const NSUInteger w=513,h=257,bpp=fi==2?8:4,row=(w*bpp+255)&~255UL;
 emit(@{@"phase":@"begin",@"format":@(formats[fi]),@"mode":@(mode)});
 MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:formats[fi] width:w height:h mipmapped:NO];td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;td.storageMode=mode==0?MTLStorageModePrivate:MTLStorageModeManaged;
 IOSurfaceRef surface=NULL;id<MTLTexture> tex=nil;
 if(mode==2) {surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{(id)kIOSurfaceWidth:@(w),(id)kIOSurfaceHeight:@(h),(id)kIOSurfaceBytesPerElement:@(bpp),(id)kIOSurfaceBytesPerRow:@(row),(id)kIOSurfaceAllocSize:@(row*h)});if(surface) tex=[dev newTextureWithDescriptor:td iosurface:surface plane:0];}
 else tex=[dev newTextureWithDescriptor:td];
 if(!tex) {emit(@{@"phase":@"unsupported",@"format":@(formats[fi]),@"mode":@(mode)});if(surface)CFRelease(surface);continue;}
 MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];pd.vertexFunction=[lib newFunctionWithName:@"v"];pd.fragmentFunction=[lib newFunctionWithName:@"f"];pd.colorAttachments[0].pixelFormat=formats[fi];
 id<MTLRenderPipelineState> base=[dev newRenderPipelineStateWithDescriptor:pd error:&err];
 pd.colorAttachments[0].blendingEnabled=YES;pd.colorAttachments[0].sourceRGBBlendFactor=MTLBlendFactorOne;pd.colorAttachments[0].destinationRGBBlendFactor=MTLBlendFactorOneMinusSourceAlpha;pd.colorAttachments[0].sourceAlphaBlendFactor=MTLBlendFactorOne;pd.colorAttachments[0].destinationAlphaBlendFactor=MTLBlendFactorOneMinusSourceAlpha;
 id<MTLRenderPipelineState> blend=[dev newRenderPipelineStateWithDescriptor:pd error:&err];
 if(!base||!blend) {emit(@{@"error":err.description});return 2;}
 id<MTLBuffer> output=[dev newBufferWithLength:row*h options:MTLResourceStorageModeManaged];memset(output.contents,0xcd,row*h);[output didModifyRange:NSMakeRange(0,row*h)];
 id<MTLCommandBuffer> cb=[queue commandBuffer];MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];pass.colorAttachments[0].texture=tex;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
 id<MTLRenderCommandEncoder> re=[cb renderCommandEncoderWithDescriptor:pass];[re setRenderPipelineState:base];uint32_t layer=0;[re setFragmentBytes:&layer length:4 atIndex:0];[re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[re setRenderPipelineState:blend];layer=1;[re setFragmentBytes:&layer length:4 atIndex:0];[re drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[re endEncoding];
 id<MTLBlitCommandEncoder> bl=[cb blitCommandEncoder];[bl copyFromTexture:tex sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1) toBuffer:output destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row*h];[bl synchronizeResource:output];if(surface)[bl synchronizeResource:tex];[bl endEncoding];
 dispatch_semaphore_t done=dispatch_semaphore_create(0);[cb addCompletedHandler:^(id<MTLCommandBuffer> unused){(void)unused;dispatch_semaphore_signal(done);}];[cb commit];if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC))) {emit(@{@"error":@"GPU deadline",@"format":@(formats[fi]),@"mode":@(mode)});return 3;}
 if(cb.status!=MTLCommandBufferStatusCompleted) {emit(@{@"error":cb.error.description?:@"command failed"});return 3;}
 unsigned cpuBad=0; if(surface) { uint32_t seed=0; IOReturn lr=IOSurfaceLock(surface,kIOSurfaceLockReadOnly,&seed); if(lr){emit(@{@"error":@"surface lock",@"status":@(lr)});return 3;} const uint8_t *sp=IOSurfaceGetBaseAddress(surface);size_t sr=IOSurfaceGetBytesPerRow(surface);for(NSUInteger y=0;y<h;y++)for(NSUInteger x=0;x<w*bpp;x++)if(sp[y*sr+x]!=((uint8_t*)output.contents)[y*row+x])cpuBad++; IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,&seed); } unsigned bad=0;float maxError=0;unsigned firstX=0,firstY=0;
 for(NSUInteger y=0;y<h;y++) for(NSUInteger x=0;x<w;x++) {
 bool c=((x/13+y/11)%2)!=0;float expect[4]={c?.1875f:.4375f,c?.1875f:.25f,c?.625f:.3125f,1};float got[4];uint8_t *p=(uint8_t*)output.contents+y*row+x*bpp;
 if(fi==2) for(unsigned k=0;k<4;k++)got[k]=halfValue(((uint16_t*)p)[k]);
 else if(fi==3) {uint32_t v;memcpy(&v,p,4);got[0]=(v&1023)/1023.f;got[1]=((v>>10)&1023)/1023.f;got[2]=((v>>20)&1023)/1023.f;got[3]=(v>>30)/3.f;}
 else for(unsigned k=0;k<4;k++)got[k]=p[fi==0&&k<3?2-k:k]/255.f;
 bool mismatch=false;for(unsigned k=0;k<4;k++){float e=fabsf(got[k]-expect[k]);if(e>maxError)maxError=e;if(!isfinite(got[k])||e>.012f)mismatch=true;}if(mismatch){if(!bad){firstX=(unsigned)x;firstY=(unsigned)y;}bad++;}
 }
 cases++;if(bad||cpuBad)failures++;emit(@{@"phase":@"result",@"format":@(formats[fi]),@"mode":@(mode),@"pixels":@(w*h),@"bad":@(bad),@"cpu_byte_mismatches":@(cpuBad),@"max_error":@(maxError),@"first_x":@(firstX),@"first_y":@(firstY)});if(surface)CFRelease(surface);
 }
 }
 emit(@{@"phase":@"done",@"cases":@(cases),@"failures":@(failures)});return failures?1:0;
}}
