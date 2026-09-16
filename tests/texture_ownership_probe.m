// Independent CPU oracle for managed texture ownership and retained LOAD contents.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static void expired(int s) { (void)s; _exit(124); }
static void emit(NSDictionary *d) {
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes,1,j.length,stdout); putchar('\n'); fflush(stdout);
}
static bool complete(id<MTLCommandBuffer> cb) {
    if(!cb)return false;
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    [cb addCompletedHandler:^(id<MTLCommandBuffer> b){(void)b;dispatch_semaphore_signal(done);}];
    [cb commit];
    if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC)) || cb.status!=MTLCommandBufferStatusCompleted) {
        emit(@{@"phase":@"error",@"error":cb.error.description?:@"GPU timeout"});return false;
    }
    [cb waitUntilCompleted];return true;
}
// Canonical RGBA bytes; deliberately independent of the shader's packed vector.
static void expected(uint8_t *p,unsigned x,unsigned y,uint32_t seed,bool bgra) {
    uint8_t r=(x*13+y*3+seed*7)&255,g=(x*5+y*17+seed*11)&255;
    uint8_t b=(x*19+y*7+seed*23)&255,a=128+((x+y+seed)&127);
    p[0]=bgra?b:r;p[1]=g;p[2]=bgra?r:b;p[3]=a;
}
static bool render(id<MTLCommandBuffer> cb,id<MTLTexture> t,id<MTLRenderPipelineState> ps,
                   uint32_t seed,bool load,MTLScissorRect rect) {
    MTLRenderPassDescriptor *p=[MTLRenderPassDescriptor renderPassDescriptor];
    p.colorAttachments[0].texture=t;
    p.colorAttachments[0].loadAction=load?MTLLoadActionLoad:MTLLoadActionClear;
    p.colorAttachments[0].storeAction=MTLStoreActionStore;
    id<MTLRenderCommandEncoder> e=[cb renderCommandEncoderWithDescriptor:p];
    if(!e)return false;
    [e setRenderPipelineState:ps];[e setScissorRect:rect];
    [e setFragmentBytes:&seed length:sizeof(seed) atIndex:0];
    [e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];[e endEncoding];return true;
}
static bool one(id<MTLDevice> dev,id<MTLCommandQueue> queue,id<MTLRenderPipelineState> ps,
                bool bgra,unsigned shape,unsigned mode,uint32_t seed,uint64_t *pixels) { @autoreleasepool {
    NSUInteger w=shape?1003:64,h=shape?769:64,row=(w*4+255)&~255UL,bytes=row*h;
    NSString *caseID=[NSString stringWithFormat:@"%@-%lux%lu-%@-%u",bgra?@"bgra":@"rgba",w,h,
                      @[@"load-only",@"cpu-only",@"cpu-and-load"][mode],seed];
    emit(@{@"phase":@"case_begin",@"case_id":caseID});
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:bgra?MTLPixelFormatBGRA8Unorm:MTLPixelFormatRGBA8Unorm width:w height:h mipmapped:NO];
    td.storageMode=MTLStorageModeManaged;td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    id<MTLTexture> t=[dev newTextureWithDescriptor:td];
    id<MTLBuffer> out=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    NSMutableData *cpu=[NSMutableData dataWithLength:bytes],*upload=[NSMutableData dataWithLength:bytes];
    if(!t||!out||!cpu||!upload)return false;
    memset(cpu.mutableBytes,0xa5,bytes);memset(out.contents,0xa5,bytes);
    [out didModifyRange:NSMakeRange(0,bytes)];
    id<MTLCommandBuffer> cb=[queue commandBuffer];
    if(!cb||!render(cb,t,ps,seed,false,(MTLScissorRect){0,0,w,h}))return false;
    id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];if(!blit)return false;
    [blit synchronizeTexture:t slice:0 level:0];[blit endEncoding];
    if(!complete(cb))return false;
    // GPU -> CPU contract: synchronization AND completed command buffer before access.
    [t getBytes:cpu.mutableBytes bytesPerRow:row fromRegion:MTLRegionMake2D(0,0,w,h) mipmapLevel:0];
    uint64_t initialBad=0,paddingBad=0;
    for(unsigned y=0;y<h;y++) {
        for(unsigned x=0;x<w;x++) {uint8_t p[4];expected(p,x,y,seed,bgra);
            if(memcmp(p,(uint8_t*)cpu.bytes+y*row+x*4,4))initialBad++;}
        for(NSUInteger x=w*4;x<row;x++)if(((uint8_t*)cpu.bytes)[y*row+x]!=0xa5)paddingBad++;
    }
    emit(@{@"phase":@"initial",@"case_id":caseID,@"pixels":@(w*h),@"bad":@(initialBad),@"padding_bad":@(paddingBad)});
    if(initialBad||paddingBad)return false;
    // CPU changes the right half; LOAD changes only a left-half inset. Both
    // regions and untouched borders must survive. No intervening GPU readback.
    NSUInteger split=w/2;
    if(mode!=0) {
        for(unsigned y=0;y<h;y++)for(unsigned x=split;x<w;x++)
            expected((uint8_t*)upload.mutableBytes+y*row+(x-split)*4,x,y,seed+101,bgra);
        [t replaceRegion:MTLRegionMake2D(split,0,w-split,h) mipmapLevel:0 withBytes:upload.bytes bytesPerRow:row];
    }
    cb=[queue commandBuffer];if(!cb)return false;
    MTLScissorRect inset={1,1,split-2,h-2};
    if(mode!=1&&!render(cb,t,ps,seed+211,true,inset))return false;
    blit=[cb blitCommandEncoder];if(!blit)return false;
    [blit copyFromTexture:t sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(w,h,1)
                toBuffer:out destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:bytes];
    [blit synchronizeResource:out];[blit synchronizeTexture:t slice:0 level:0];[blit endEncoding];
    if(!complete(cb))return false;
    memset(cpu.mutableBytes,0xa5,bytes);
    [t getBytes:cpu.mutableBytes bytesPerRow:row fromRegion:MTLRegionMake2D(0,0,w,h) mipmapLevel:0];
    uint64_t bad=0,cpuBad=0; paddingBad=0;
    for(unsigned y=0;y<h;y++) {
        for(unsigned x=0;x<w;x++) {
            uint32_t s=seed;
            if(mode!=0&&x>=split)s=seed+101;
            if(mode!=1&&x>=1&&x<split-1&&y>=1&&y<h-1)s=seed+211;
            uint8_t p[4];expected(p,x,y,s,bgra);
            if(memcmp(p,(uint8_t*)out.contents+y*row+x*4,4))bad++;
            if(memcmp(p,(uint8_t*)cpu.bytes+y*row+x*4,4))cpuBad++;
        }
        for(NSUInteger x=w*4;x<row;x++) {
            if(((uint8_t*)out.contents)[y*row+x]!=0xa5)paddingBad++;
            if(((uint8_t*)cpu.bytes)[y*row+x]!=0xa5)paddingBad++;
        }
    }
    *pixels+=w*h;
    emit(@{@"phase":@"case",@"case_id":caseID,@"pixels":@(w*h),@"gpu_copy_bad":@(bad),@"cpu_read_bad":@(cpuBad),@"padding_bad":@(paddingBad)});
    return bad==0&&cpuBad==0&&paddingBad==0;
}}
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired);alarm(180);
    if(argc!=3)return 2;
    uint64_t wanted=strtoull(argv[1],NULL,0);uint32_t seed=(uint32_t)strtoul(argv[2],NULL,0);
    id<MTLDevice> dev=nil;for(id<MTLDevice> d in MTLCopyAllDevices())if(d.registryID==wanted)dev=d;
    if(!dev)return 2;
    NSString *source=@"#include <metal_stdlib>\nusing namespace metal;\n"
    "vertex float4 v(uint i [[vertex_id]]) {float2 p[3]={float2(-1,-1),float2(3,-1),float2(-1,3)};return float4(p[i],0,1);}\n"
    "fragment float4 f(float4 pos [[position]],constant uint &s [[buffer(0)]]) {uint2 p=uint2(pos.xy);"
    "uint4 c=uint4(p.x*13+p.y*3+s*7,p.x*5+p.y*17+s*11,p.x*19+p.y*7+s*23,128+((p.x+p.y+s)&127));"
    "return float4(c & uint4(255))/255.0;}\n";
    NSError *error=nil;id<MTLLibrary> lib=[dev newLibraryWithSource:source options:nil error:&error];
    if(!lib){emit(@{@"error":error.description?:@"library failed"});return 2;}
    id<MTLCommandQueue> queue=[dev newCommandQueue];if(!queue)return 2;
    uint64_t pixels=0;unsigned cases=0;
    emit(@{@"phase":@"begin",@"registry_id":@(wanted),@"pid":@(getpid()),@"seed":@(seed),@"expected_cases":@48});
    for(unsigned format=0;format<2;format++) {
        MTLRenderPipelineDescriptor *pd=[MTLRenderPipelineDescriptor new];
        pd.vertexFunction=[lib newFunctionWithName:@"v"];pd.fragmentFunction=[lib newFunctionWithName:@"f"];
        pd.colorAttachments[0].pixelFormat=format?MTLPixelFormatBGRA8Unorm:MTLPixelFormatRGBA8Unorm;
        id<MTLRenderPipelineState> ps=[dev newRenderPipelineStateWithDescriptor:pd error:&error];
        if(!ps){emit(@{@"error":error.description?:@"pipeline failed"});return 2;}
        for(unsigned shape=0;shape<2;shape++)for(unsigned round=0;round<4;round++)for(unsigned mode=0;mode<3;mode++) {
            if(!one(dev,queue,ps,format,shape,mode,seed+round*997,&pixels))return 3;cases++;
        }
    }
    emit(@{@"phase":@"done",@"passed":@(cases==48),@"cases":@(cases),@"case_pixels":@(pixels),@"pixel_comparisons":@(pixels*3),@"readbacks_per_case":@3,@"seed":@(seed),@"pid":@(getpid())});return cases==48?0:4;
}}
