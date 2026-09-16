// Explicit blit -> compute -> blit fences on untracked private resources.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s){(void)s;_exit(124);}
static void emit(NSDictionary *d){NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];fwrite(j.bytes,1,j.length,stdout);putchar('\n');fflush(stdout);}
static uint32_t value(uint32_t i,uint32_t seed){uint32_t x=i^(seed*0x9e3779b9U);x^=x>>16;x*=0x7feb352dU;x^=x>>15;x*=0x846ca68bU;return x^(x>>16);}
int main(int argc,const char **argv){@autoreleasepool{
    signal(SIGALRM,expired);alarm(180);
    uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;
    id<MTLDevice> dev=nil;for(id<MTLDevice>d in MTLCopyAllDevices())if(d.registryID==wanted)dev=d;
    if(!dev)return 2;
    NSError *error=nil;
    NSString *source=@"#include <metal_stdlib>\nusing namespace metal;\nkernel void transform(device const uint *a [[buffer(0)]], device uint *b [[buffer(1)]], constant uint &seed [[buffer(2)]], uint i [[thread_position_in_grid]]) { b[i]=(a[i]^seed)*1664525u+1013904223u; }";
    id<MTLLibrary> lib=[dev newLibraryWithSource:source options:nil error:&error];
    id<MTLFunction> fn=[lib newFunctionWithName:@"transform"];
    id<MTLComputePipelineState> pipeline=fn?[dev newComputePipelineStateWithFunction:fn error:&error]:nil;
    id<MTLCommandQueue> queue=[dev newCommandQueue];
    id<MTLFence> uploadFence=[dev newFence],computeFence=[dev newFence];
    if(!pipeline||!queue||!uploadFence||!computeFence){emit(@{@"phase":@"error",@"error":error.description?:@"pipeline, queue or fence unavailable"});return 2;}
    const NSUInteger bytes=4*1024*1024,words=bytes/4;
    id<MTLBuffer> input=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    id<MTLBuffer> a=[dev newBufferWithLength:bytes options:MTLResourceStorageModePrivate|MTLResourceHazardTrackingModeUntracked];
    id<MTLBuffer> b=[dev newBufferWithLength:bytes options:MTLResourceStorageModePrivate|MTLResourceHazardTrackingModeUntracked];
    id<MTLBuffer> output=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    if(!input||!a||!b||!output||a.hazardTrackingMode!=MTLHazardTrackingModeUntracked||b.hazardTrackingMode!=MTLHazardTrackingModeUntracked)return 2;
    for(unsigned round=1;round<=128;round++){@autoreleasepool{
        for(uint32_t i=0;i<words;i++)((uint32_t*)input.contents)[i]=value(i,round);
        [input didModifyRange:NSMakeRange(0,bytes)];
        id<MTLCommandBuffer> cb=[queue commandBuffer];if(!cb)return 2;
        id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];if(!blit)return 2;
        [blit copyFromBuffer:input sourceOffset:0 toBuffer:a destinationOffset:0 size:bytes];
        [blit updateFence:uploadFence];[blit endEncoding];
        id<MTLComputeCommandEncoder> compute=[cb computeCommandEncoder];if(!compute)return 2;
        [compute waitForFence:uploadFence];[compute setComputePipelineState:pipeline];
        [compute setBuffer:a offset:0 atIndex:0];[compute setBuffer:b offset:0 atIndex:1];
        uint32_t seed=round*0x9e3779b9U;[compute setBytes:&seed length:sizeof(seed) atIndex:2];
        NSUInteger width=MIN((NSUInteger)256,pipeline.maxTotalThreadsPerThreadgroup);
        [compute dispatchThreads:MTLSizeMake(words,1,1) threadsPerThreadgroup:MTLSizeMake(width,1,1)];
        [compute updateFence:computeFence];[compute endEncoding];
        blit=[cb blitCommandEncoder];if(!blit)return 2;
        [blit waitForFence:computeFence];
        [blit copyFromBuffer:b sourceOffset:0 toBuffer:output destinationOffset:0 size:bytes];
        [blit synchronizeResource:output];[blit endEncoding];
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        [cb addCompletedHandler:^(id<MTLCommandBuffer> c){(void)c;dispatch_semaphore_signal(done);}];[cb commit];
        if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC))||cb.status!=MTLCommandBufferStatusCompleted){emit(@{@"phase":@"error",@"round":@(round),@"error":cb.error.description?:@"GPU timeout"});return 3;}
        [cb waitUntilCompleted];
        uint64_t bad=0;for(uint32_t i=0;i<words;i++){
            uint32_t expected=(value(i,round)^seed)*1664525U+1013904223U;
            if(((const uint32_t*)output.contents)[i]!=expected)bad++;
        }
        emit(@{@"phase":@"round",@"round":@(round),@"bad":@(bad)});if(bad)return 4;
    }}
    emit(@{@"phase":@"done",@"passed":@YES,@"rounds":@128,@"values_checked":@(128ULL*1024*1024),@"pid":@(getpid()),@"scope":@"one queue, untracked private buffers, blit-compute-blit fences"});return 0;
}}
