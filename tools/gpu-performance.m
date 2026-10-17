// Same-workload GPU timing benchmark; desktop probe supplies audited render shaders.
#define main desktop_evidence_main
#include "../tests/desktop_metal_probe.m"
#undef main

static void benchFail(NSString *message) {
    fprintf(stderr, "RGPU_BENCH_ERROR %s\n", message.UTF8String);
    exit(1);
}
static double finishCommand(id<MTLCommandBuffer> command) {
    [command commit]; [command waitUntilCompleted];
    if (command.status != MTLCommandBufferStatusCompleted) benchFail(command.error.description ?: @"command failed");
    double seconds = command.GPUEndTime - command.GPUStartTime;
    if (!isfinite(seconds) || seconds <= 0) benchFail(@"GPU timestamps unavailable");
    return seconds;
}
static NSDictionary *stats(NSArray<NSNumber *> *values) {
    NSArray<NSNumber *> *sorted = [values sortedArrayUsingSelector:@selector(compare:)];
    if (sorted.count != 10) benchFail(@"sample count");
    double median = (sorted[4].doubleValue + sorted[5].doubleValue) / 2;
    return @{ @"median": @(median), @"min": sorted.firstObject, @"max": sorted.lastObject, @"samples": values };
}
static NSDictionary *renderBench(id<MTLDevice> device, id<MTLCommandQueue> queue) {
    NSMutableDictionary *errors = [NSMutableDictionary dictionary];
    id<MTLLibrary> library = compileLibrary(device, kShaderSource, @"render", errors);
    id<MTLRenderPipelineState> ramp = renderPipeline(device, library, @"fullscreen", @"ramp");
    id<MTLRenderPipelineState> solid = renderPipeline(device, library, @"points", @"solid");
    if (!ramp || !solid) benchFail(errors.description);
    const NSUInteger width=1280, height=1024, triangles=20000, batch=64;
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];
    td.storageMode=MTLStorageModePrivate; td.usage=MTLTextureUsageRenderTarget;
    id<MTLTexture> target=[device newTextureWithDescriptor:td];
    id<MTLBuffer> vertices=[device newBufferWithLength:triangles*3*4*sizeof(float) options:MTLResourceStorageModeShared];
    if (!target || !vertices) benchFail(@"render allocation");
    float *v=vertices.contents; srand48(0x52475055);
    for (NSUInteger t=0;t<triangles;t++) {
        float cx=(float)(drand48()*2-1),cy=(float)(0.82+drand48()*0.16);
        const float dx[]={0,.004f,-.004f},dy[]={.008f,-.004f,-.004f};
        for (NSUInteger k=0;k<3;k++) {float *p=v+(t*3+k)*4;p[0]=cx+dx[k];p[1]=cy+dy[k];p[2]=0;p[3]=1;}
    }
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    NSMutableArray *gpu=[NSMutableArray array],*wall=[NSMutableArray array];
    const float uniforms[]={width,height,.25f,0};
    for (NSUInteger sample=0;sample<12;sample++) {
        @autoreleasepool {
            double start=CACurrentMediaTime();id<MTLCommandBuffer> cb=[queue commandBuffer];
            for (NSUInteger frame=0;frame<batch;frame++) {
                id<MTLRenderCommandEncoder> e=[cb renderCommandEncoderWithDescriptor:pass];
                [e setRenderPipelineState:ramp];[e setFragmentBytes:uniforms length:sizeof(uniforms) atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
                [e setRenderPipelineState:solid];[e setVertexBuffer:vertices offset:0 atIndex:0];[e drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:triangles*3];[e endEncoding];
            }
            double seconds=finishCommand(cb),elapsed=CACurrentMediaTime()-start;
            if(sample>=2){[gpu addObject:@(batch/seconds)];[wall addObject:@(batch/elapsed)];}
        }
    }
    id<MTLBuffer> readback=[device newBufferWithLength:width*height*4 options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb=[queue commandBuffer];id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];
    [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(width,height,1) toBuffer:readback destinationOffset:0 destinationBytesPerRow:width*4 destinationBytesPerImage:width*height*4];[blit endEncoding];finishCommand(cb);
    const uint8_t *pixels=readback.contents;NSUInteger checked=0,wrong=0;
    for(NSUInteger y=200;y<height;y+=37)for(NSUInteger x=3;x<width;x+=41){const uint8_t *p=pixels+(y*width+x)*4;int r=(int)lround(fmod((x+.5)/64,1)*255),g=(int)lround(fmod((y+.5)/64,1)*255);checked++;wrong+=abs(p[2]-r)>1||abs(p[1]-g)>1||abs(p[0]-64)>1||p[3]!=255;}
    NSUInteger yellow=0;
    for(NSUInteger y=12;y<90;y+=3)for(NSUInteger x=0;x<width;x+=7){const uint8_t *p=pixels+(y*width+x)*4;yellow+=p[2]>250&&p[1]>250&&p[0]<5;}
    if(wrong||yellow<4000)benchFail(@"render readback/triangle band mismatch");
    return @{ @"width":@(width),@"height":@(height),@"triangles_per_frame":@(triangles+1),@"frames_per_batch":@(batch),@"gpu_fps":stats(gpu),@"wall_fps":stats(wall),@"pixels_checked":@(checked),@"triangle_band_yellow_samples":@(yellow),@"mismatches":@(wrong) };
}
static NSDictionary *computeBench(id<MTLDevice> device,id<MTLCommandQueue> queue) {
    NSString *source=@"#include <metal_stdlib>\nusing namespace metal;\nstruct P {uint count;uint iterations;float a;float b;};\nkernel void arithmetic(device const float *input[[buffer(0)]],device float4 *output[[buffer(1)]],constant P &p[[buffer(2)]],uint id[[thread_position_in_grid]]) {if(id>=p.count)return;float x=input[id];float4 v0=x+float4(0,.01,.02,.03),v1=x+float4(.04,.05,.06,.07),v2=x+float4(.08,.09,.10,.11),v3=x+float4(.12,.13,.14,.15);for(uint i=0;i<p.iterations;i++){v0=fma(v0,p.a,p.b);v1=fma(v1,p.a,p.b);v2=fma(v2,p.a,p.b);v3=fma(v3,p.a,p.b);}output[id*4]=v0;output[id*4+1]=v1;output[id*4+2]=v2;output[id*4+3]=v3;}\n";
    MTLCompileOptions *options=[MTLCompileOptions new];options.fastMathEnabled=NO;NSError *error=nil;
    id<MTLLibrary> library=[device newLibraryWithSource:source options:options error:&error];
    id<MTLComputePipelineState> pipeline=library?[device newComputePipelineStateWithFunction:[library newFunctionWithName:@"arithmetic"] error:&error]:nil;
    if(!pipeline)benchFail(error.description ?: @"compute pipeline");
    struct {uint32_t count,iterations;float a,b;} p={131072,256,.99991f,.00011f};
    const NSUInteger batch=8;id<MTLBuffer> input=[device newBufferWithLength:p.count*sizeof(float) options:MTLResourceStorageModeShared];id<MTLBuffer> output=[device newBufferWithLength:p.count*16*sizeof(float) options:MTLResourceStorageModeShared];
    if(!input||!output)benchFail(@"compute allocation");float *in=input.contents;for(uint32_t i=0;i<p.count;i++)in[i]=.2f+(i%1024)*.0001f;
    NSMutableArray *gpu=[NSMutableArray array],*wall=[NSMutableArray array];
    const double operations=(double)p.count*p.iterations*16*2*batch;
    NSUInteger group=MIN((NSUInteger)256,pipeline.maxTotalThreadsPerThreadgroup);
    for(NSUInteger sample=0;sample<12;sample++){@autoreleasepool{
        double start=CACurrentMediaTime();id<MTLCommandBuffer> cb=[queue commandBuffer];
        for(NSUInteger dispatch=0;dispatch<batch;dispatch++){id<MTLComputeCommandEncoder> e=[cb computeCommandEncoder];[e setComputePipelineState:pipeline];[e setBuffer:input offset:0 atIndex:0];[e setBuffer:output offset:0 atIndex:1];[e setBytes:&p length:sizeof(p) atIndex:2];[e dispatchThreads:MTLSizeMake(p.count,1,1) threadsPerThreadgroup:MTLSizeMake(group,1,1)];[e endEncoding];}
        double seconds=finishCommand(cb),elapsed=CACurrentMediaTime()-start;if(sample>=2){[gpu addObject:@(operations/seconds/1e9)];[wall addObject:@(operations/elapsed/1e9)];}
    }}
    float *out=output.contents;NSUInteger checked=0,wrong=0;
    for(uint32_t i=0;i<p.count;i++)for(uint32_t lane=0;lane<16;lane++)if(!isfinite(out[i*16+lane]))benchFail(@"nonfinite compute output");
    for(uint32_t i=0;i<p.count;i+=257)for(uint32_t lane=0;lane<16;lane++){float expected=in[i]+lane*.01f;for(uint32_t step=0;step<p.iterations;step++)expected=fmaf(expected,p.a,p.b);checked++;wrong+=fabsf(out[i*16+lane]-expected)>3e-4f;}
    if(wrong)benchFail(@"compute readback mismatch");
    return @{ @"threads":@(p.count),@"iterations":@(p.iterations),@"float_lanes":@16,@"flops_per_fma":@2,@"dispatches_per_batch":@(batch),@"gpu_gflops":stats(gpu),@"wall_gflops":stats(wall),@"values_checked":@(checked),@"mismatches":@(wrong),@"fast_math":@NO };
}
int main(int argc,const char *argv[]) {@autoreleasepool{
    if(argc!=2)benchFail(@"expected run ID");signal(SIGALRM,deadline);alarm(90);
    id<MTLDevice> device=MTLCreateSystemDefaultDevice();if(!device||![device.name isEqualToString:@"AMD Radeon Navi23"]||![device supportsFamily:MTLGPUFamilyMetal3])benchFail(@"unexpected GPU");
    id activity=[[NSProcessInfo processInfo] beginActivityWithOptions:NSActivityUserInitiated|NSActivityLatencyCritical|NSActivityIdleSystemSleepDisabled reason:@"Matched GPU benchmark"];
    id<MTLCommandQueue> queue=[device newCommandQueue];if(!queue)benchFail(@"queue");
    CFDictionaryRef session=CGSessionCopyCurrentDictionary();NSDictionary *sessionInfo=CFBridgingRelease(session);
    NSDictionary *result=@{ @"schema":@1,@"run_id":[NSString stringWithUTF8String:argv[1]],@"uid":@(getuid()),@"device":device.name,@"registry_id":@(device.registryID),@"session_locked":sessionInfo[@"CGSSessionScreenIsLocked"] ?: [NSNull null],@"render":renderBench(device,queue),@"compute":computeBench(device,queue),@"passed":@YES };
    NSData *data=reportJSON(result);printf("RGPU_GPU_BENCH_RESULT %.*s\n",(int)data.length,(const char*)data.bytes);fflush(stdout);[[NSProcessInfo processInfo] endActivity:activity];return 0;
}}
