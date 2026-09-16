// Bounded process-local Metal allocation/release qualification, not global VRAM accounting.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <signal.h>
#include <unistd.h>
#include <mach/mach.h>
static void expired(int s) { (void)s; _exit(124); }
static void emit(NSDictionary *d) {
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes,1,j.length,stdout); putchar('\n'); fflush(stdout);
}
static uint32_t value(uint32_t i, uint32_t seed) {
    uint32_t x=i ^ (seed*0x9e3779b9U); x^=x>>16; x*=0x7feb352dU;
    x^=x>>15; x*=0x846ca68bU; return x^(x>>16);
}
static uint64_t rss(void) {
    mach_task_basic_info_data_t info={0}; mach_msg_type_number_t n=MACH_TASK_BASIC_INFO_COUNT;
    return task_info(mach_task_self(),MACH_TASK_BASIC_INFO,(task_info_t)&info,&n)==KERN_SUCCESS?info.resident_size:0;
}
static bool batch(id<MTLDevice> dev, unsigned round, uint64_t *peak) { @autoreleasepool {
    const NSUInteger bytes=4*1024*1024, words=bytes/4, sets=4;
    id<MTLCommandQueue> queue=[dev newCommandQueue];
    id<MTLCommandBuffer> cb=[queue commandBuffer];
    id<MTLBlitCommandEncoder> blit=[cb blitCommandEncoder];
    NSMutableArray<id<MTLBuffer>> *inputs=[NSMutableArray new], *privateBuffers=[NSMutableArray new], *outputs=[NSMutableArray new];
    if(!queue || !cb || !blit) return false;
    for(unsigned s=0;s<sets;s++) {
        id<MTLBuffer> input=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
        id<MTLBuffer> intermediate=[dev newBufferWithLength:bytes options:MTLResourceStorageModePrivate];
        id<MTLBuffer> output=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
        if(!input || !intermediate || !output) return false;
        [inputs addObject:input]; [privateBuffers addObject:intermediate]; [outputs addObject:output];
        uint32_t *data=input.contents;
        for(uint32_t i=0;i<words;i++) data[i]=value(i,round*sets+s+1);
        [input didModifyRange:NSMakeRange(0,bytes)];
        [blit copyFromBuffer:input sourceOffset:0 toBuffer:intermediate destinationOffset:0 size:bytes];
        [blit copyFromBuffer:intermediate sourceOffset:0 toBuffer:output destinationOffset:0 size:bytes];
        [blit synchronizeResource:output];
    }
    *peak=dev.currentAllocatedSize;
    [blit endEncoding];
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    [cb addCompletedHandler:^(id<MTLCommandBuffer> b){(void)b;dispatch_semaphore_signal(done);}];
    [cb commit];
    if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC)) || cb.status!=MTLCommandBufferStatusCompleted) {
        emit(@{@"phase":@"error",@"round":@(round),@"error":cb.error.description?:@"command timeout"}); return false;
    }
    // Ensure the handler returns before its queue and resources leave this pool.
    [cb waitUntilCompleted];
    uint64_t bad=0;
    for(unsigned s=0;s<sets;s++) {
        const uint32_t *data=outputs[s].contents;
        for(uint32_t i=0;i<words;i++) if(data[i]!=value(i,round*sets+s+1)) bad++;
    }
    emit(@{@"phase":@"batch",@"round":@(round),@"values_checked":@(words*sets),@"bad":@(bad),@"peak_allocated":@(*peak)});
    return bad==0;
}}
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired); alarm(150);
    uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;
    id<MTLDevice> dev=nil;
    for(id<MTLDevice> d in MTLCopyAllDevices()) if(d.registryID==wanted) dev=d;
    if(!dev) return 2;
    const unsigned rounds=32, warmup=3;
    const uint64_t tolerance=4*1024*1024;
    uint64_t baseline=dev.currentAllocatedSize, maxAfter=0, maxPeak=0;
    emit(@{@"phase":@"begin",@"registry_id":@(dev.registryID),@"pid":@(getpid()),@"initial_allocated":@(baseline),@"rss":@(rss()),@"rounds":@(rounds),@"warmup":@(warmup),@"live_resource_bytes":@(48*1024*1024),@"settle_tolerance_bytes":@(tolerance)});
    for(unsigned round=0;round<warmup+rounds;round++) {
        uint64_t peak=0;
        if(!batch(dev,round,&peak)) return 3;
        // Delayed object retirement is allowed up to two seconds, with every final sample recorded.
        uint64_t after=dev.currentAllocatedSize;
        unsigned polls=0;
        do { usleep(100000); after=dev.currentAllocatedSize; polls++; }
        while(after>baseline+tolerance && polls<20);
        if(round==warmup-1) baseline=after;
        if(round>=warmup) {
            maxAfter=MAX(maxAfter,after); maxPeak=MAX(maxPeak,peak);
            if(after>baseline+tolerance || peak<baseline+32*1024*1024) {
                emit(@{@"phase":@"error",@"round":@(round),@"baseline":@(baseline),@"after":@(after),@"peak":@(peak),@"error":@"allocation did not return within tolerance or peak did not establish pressure"}); return 4;
            }
        }
        emit(@{@"phase":@"released",@"round":@(round),@"allocated":@(after),@"baseline":@(baseline),@"rss":@(rss()),@"settle_polls":@(polls)});
    }
    emit(@{@"phase":@"done",@"passed":@YES,@"rounds":@(rounds),@"warmup":@(warmup),@"baseline":@(baseline),@"max_after":@(maxAfter),@"max_peak":@(maxPeak),@"measured_values_checked":@(32ULL*4*1024*1024),@"pid":@(getpid()),@"scope":@"process-local currentAllocatedSize; managed/private buffer copies only"});
    return 0;
}}
