// Distinct-seed, separate-process feedback readback for resource-isolation coverage.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurface.h>
#include <math.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s) { (void)s; _exit(124); }
static void emit(NSDictionary *d) {
    NSData *j = [NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes, 1, j.length, stdout); putchar('\n'); fflush(stdout);
}
static float quantize(float x) { return roundf(fminf(1, fmaxf(0,x))*255)/255; }
int main(int argc, const char **argv) { @autoreleasepool {
    signal(SIGALRM, expired); alarm(150);
    uint64_t wanted = argc > 1 ? strtoull(argv[1], NULL, 0) : 0;
    uint32_t seed=argc>3?(uint32_t)strtoul(argv[3],NULL,0):0;
    id<MTLDevice> dev = nil;
    for (id<MTLDevice> d in MTLCopyAllDevices()) if (d.registryID == wanted) dev = d;
    if (!dev) return 2;
    NSString *source = @"#include <metal_stdlib>\nusing namespace metal;\n"
    "struct V { float4 p [[position]]; half4 color; };\n"
    "vertex V v(uint i [[vertex_id]]) {float2 p[4]={float2(-1,-1),float2(1,-1),float2(1,1),float2(-1,1)};return {float4(p[i],0,1),half4(28.0h/255.0h,28.0h/255.0h,28.0h/255.0h,1)};}\n"
    "fragment half4 base(V in [[stage_in]],constant uint &seed [[buffer(1)]]) {uint2 p=uint2(in.p.xy);return half4(half((p.x/20+seed)%17)/16,half((p.y/20+seed*3)%13)/12,half((p.x/20+p.y/20+seed*7)%11)/10,1);}\n"
    "fragment half4 solid(V in [[stage_in]],constant half4 &c [[buffer(0)]]) {return c;}\n"
    "fragment half4 feedback(V in [[stage_in]],texture2d<half,access::read> dest [[texture(0)]]) {return max(dest.read(uint2(in.p.xy)),half4(28.0h/255.0h,28.0h/255.0h,28.0h/255.0h,1));}\n";
    NSError *error = nil;
    id<MTLLibrary> lib = [dev newLibraryWithSource:source options:nil error:&error];
    if (!lib) { emit(@{@"error":error.description}); return 2; }
    MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
    pd.vertexFunction = [lib newFunctionWithName:@"v"];
    pd.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    pd.fragmentFunction = [lib newFunctionWithName:@"base"];
    id<MTLRenderPipelineState> base = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
    id<MTLLibrary> native = [dev newLibraryWithFile:@"/System/Library/Frameworks/QuartzCore.framework/Versions/A/Resources/default.metallib" error:&error];
    MTLFunctionConstantValues *fc = [MTLFunctionConstantValues new];
    bool no = false, yes = true; uint8_t zero = 0, one = 1, textureFunction = 16, blendFunction = 18;
    for (unsigned i=0;i<=27;i++) if(i==0||i==4||(i>=7&&i<=27)) [fc setConstantValue:&no type:MTLDataTypeBool atIndex:i];
    for (unsigned i=28;i<=64;i++) if(i==28||i==29||i==31||i==32||(i>=34&&i<=36)||(i>=45&&i<=56)||i==63||i==64) [fc setConstantValue:&zero type:MTLDataTypeUChar atIndex:i];
    for (unsigned i=37;i<=43;i++) [fc setConstantValue:&no type:MTLDataTypeBool atIndex:i];
    [fc setConstantValue:&zero type:MTLDataTypeUChar atIndex:3];
    [fc setConstantValue:&one type:MTLDataTypeUChar atIndex:5];
    [fc setConstantValue:&yes type:MTLDataTypeBool atIndex:12];
    [fc setConstantValue:&one type:MTLDataTypeUChar atIndex:35];
    [fc setConstantValue:&textureFunction type:MTLDataTypeUChar atIndex:28];
    [fc setConstantValue:&blendFunction type:MTLDataTypeUChar atIndex:29];
    pd.fragmentFunction = [native newFunctionWithName:@"fixed_frag_lph_cph" constantValues:fc error:&error];
    if (!pd.fragmentFunction) {emit(@{@"error":error.description?:@"native specialization failed"});return 2;}
    if (argc>2 && atoi(argv[2])==1) pd.fragmentFunction=[lib newFunctionWithName:@"feedback"];
    id<MTLRenderPipelineState> feedback = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
    pd.fragmentFunction = [lib newFunctionWithName:@"solid"];
    pd.colorAttachments[0].blendingEnabled = YES;
    pd.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorOne;
    pd.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    pd.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
    pd.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    id<MTLRenderPipelineState> solid = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
    if (!base || !feedback || !solid) {emit(@{@"error":error.description});return 2;}
    id<MTLCommandQueue> queue = [dev newCommandQueue];
    const NSUInteger width=1280,height=1024,row=width*4;
    uint16_t indices[] = {0,1,2,0,2,3};
    id<MTLBuffer> ib = [dev newBufferWithBytes:indices length:sizeof(indices) options:MTLResourceStorageModeShared];
    unsigned failures=0;
    for (unsigned storage=0;storage<3;storage++) for (unsigned barrier=0;barrier<4;barrier++) { @autoreleasepool {
        emit(@{@"phase":@"begin",@"storage":@(storage),@"barrier":@(barrier)});
        MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];
        td.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
        td.storageMode=storage==0?MTLStorageModePrivate:MTLStorageModeManaged;
        IOSurfaceRef surface=NULL; id<MTLTexture> target;
        if(storage==2) {
            surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),(id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(row),(id)kIOSurfaceAllocSize:@(row*height)});
            target=[dev newTextureWithDescriptor:td iosurface:surface plane:0];
        } else target=[dev newTextureWithDescriptor:td];
        if(!target)return 2;
        id<MTLBuffer> out=[dev newBufferWithLength:row*height options:MTLResourceStorageModeManaged];
        MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture=target;
        pass.colorAttachments[0].loadAction=MTLLoadActionClear;
        pass.colorAttachments[0].storeAction=MTLStoreActionStore;
        id<MTLCommandBuffer> cb=[queue commandBuffer];
        id<MTLRenderCommandEncoder> enc=[cb renderCommandEncoderWithDescriptor:pass];
        [enc setRenderPipelineState:base]; [enc setFragmentBytes:&seed length:sizeof(seed) atIndex:1];
        [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:6 indexType:MTLIndexTypeUInt16 indexBuffer:ib indexBufferOffset:0];
        // Exact observed first-panel colors, converted to half by the CPU compiler.
        _Float16 shade[4]={24.0/255,24.0/255,24.0/255,153.0/255};
        _Float16 tint[4]={2.0/255,3.0/255,7.0/255,13.0/255};
        for(unsigned iteration=0;iteration<1;iteration++) {
            [enc setViewport:(MTLViewport){105,303,220,500,0,1}];
            [enc setScissorRect:(MTLScissorRect){105,303,220,500}];
            [enc setRenderPipelineState:solid];
            [enc setFragmentBytes:shade length:sizeof(shade) atIndex:0];
            [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:6 indexType:MTLIndexTypeUInt16 indexBuffer:ib indexBufferOffset:0];
            if(barrier==2) {
                [enc endEncoding];pass.colorAttachments[0].loadAction=MTLLoadActionLoad;
                enc=[cb renderCommandEncoderWithDescriptor:pass];
                [enc setViewport:(MTLViewport){105,303,220,500,0,1}];
                [enc setScissorRect:(MTLScissorRect){105,303,220,500}];
            } else if (barrier==3) {
                [enc textureBarrier];
            } else {
                MTLBarrierScope scope=barrier==0?MTLBarrierScopeRenderTargets:(MTLBarrierScopeRenderTargets|MTLBarrierScopeTextures|MTLBarrierScopeBuffers);
                [enc memoryBarrierWithScope:scope afterStages:MTLRenderStageFragment beforeStages:MTLRenderStageFragment];
            }
            uint8_t uniforms[224]={0}; [enc setFragmentBytes:uniforms length:sizeof(uniforms) atIndex:1]; [enc setRenderPipelineState:feedback];[enc setFragmentTexture:target atIndex:0];
            [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:6 indexType:MTLIndexTypeUInt16 indexBuffer:ib indexBufferOffset:0];
            [enc setRenderPipelineState:solid];[enc setFragmentBytes:tint length:sizeof(tint) atIndex:0];
            [enc drawIndexedPrimitives:MTLPrimitiveTypeTriangle indexCount:6 indexType:MTLIndexTypeUInt16 indexBuffer:ib indexBufferOffset:0];
        }
        [enc endEncoding];
        id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];
        [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(width,height,1) toBuffer:out destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:row*height];
        [blit synchronizeResource:out];[blit endEncoding];
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        [cb addCompletedHandler:^(id<MTLCommandBuffer> b){(void)b;dispatch_semaphore_signal(done);}];[cb commit];
        if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC))||cb.status!=MTLCommandBufferStatusCompleted){emit(@{@"error":cb.error.description?:@"GPU timeout"});return 3;}
        unsigned bad=0,firstX=0,firstY=0;float maxError=0;
        for(unsigned y=303;y<803;y++)for(unsigned x=105;x<325;x++) {
            float expect[3]={quantize(((x/20+seed)%17)/16.f),quantize(((y/20+seed*3)%13)/12.f),quantize(((x/20+y/20+seed*7)%11)/10.f)};
            for(unsigned iteration=0;iteration<1;iteration++)for(unsigned k=0;k<3;k++) {
                expect[k]=quantize((float)shade[k]+expect[k]*(1-(float)shade[3]));
                expect[k]=quantize(fmaxf(expect[k],28.f/255));
                expect[k]=quantize((float)tint[k]+expect[k]*(1-(float)tint[3]));
            }
            const uint8_t *pixel=(const uint8_t*)out.contents+y*row+x*4;bool wrong=false;
            for(unsigned k=0;k<3;k++){float e=fabsf(pixel[2-k]/255.f-expect[k]);maxError=fmaxf(maxError,e);if(e>2.1f/255)wrong=true;}
            if(wrong){if(!bad){firstX=x;firstY=y;emit(@{@"phase":@"first_mismatch",@"got":@[@(pixel[2]),@(pixel[1]),@(pixel[0])],@"expected":@[@(expect[0]*255),@(expect[1]*255),@(expect[2]*255)]});}bad++;}
        }
        if(bad)failures++;
        emit(@{@"phase":@"result",@"storage":@(storage),@"barrier":@(barrier),@"pixels":@110000,@"bad":@(bad),@"max_error":@(maxError),@"first_x":@(firstX),@"first_y":@(firstY)});
        if(surface)CFRelease(surface);
    }}
    emit(@{@"phase":@"done",@"cases":@12,@"failures":@(failures),@"seed":@(seed),@"pid":@(getpid())});return failures?1:0;
}}
