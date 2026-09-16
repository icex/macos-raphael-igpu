// Consumer is submitted before producer; only the GPU event orders buffer writes and reads.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s){(void)s;_exit(124);}
static void emit(NSDictionary *d){NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];fwrite(j.bytes,1,j.length,stdout);putchar('\n');fflush(stdout);}
static uint32_t value(uint32_t i,uint32_t seed){uint32_t x=i^(seed*0x9e3779b9U);x^=x>>16;x*=0x7feb352dU;x^=x>>15;x*=0x846ca68bU;return x^(x>>16);}
int main(int argc,const char **argv){@autoreleasepool{
    signal(SIGALRM,expired);alarm(120);
    uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;
    id<MTLDevice> dev=nil;for(id<MTLDevice>d in MTLCopyAllDevices())if(d.registryID==wanted)dev=d;
    if(!dev)return 2;
    id<MTLCommandQueue> producer=[dev newCommandQueue],consumer=[dev newCommandQueue];
    id<MTLSharedEvent> event=[dev newSharedEvent];
    if(!producer||!consumer||!event){emit(@{@"phase":@"error",@"error":@"queues or shared event unavailable"});return 2;}
    const NSUInteger bytes=4*1024*1024,words=bytes/4;
    id<MTLBuffer> input=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    id<MTLBuffer> gpu=[dev newBufferWithLength:bytes options:MTLResourceStorageModePrivate];
    id<MTLBuffer> output=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    if(!input||!gpu||!output)return 2;
    for(unsigned round=1;round<=32;round++){@autoreleasepool{
        for(uint32_t i=0;i<words;i++)((uint32_t*)input.contents)[i]=value(i,round);
        [input didModifyRange:NSMakeRange(0,bytes)];
        id<MTLCommandBuffer> write=[producer commandBuffer],read=[consumer commandBuffer];
        if(!write||!read)return 2;
        id<MTLBlitCommandEncoder> b=[write blitCommandEncoder];if(!b)return 2;
        [b copyFromBuffer:input sourceOffset:0 toBuffer:gpu destinationOffset:0 size:bytes];[b endEncoding];
        [write encodeSignalEvent:event value:round];
        [read encodeWaitForEvent:event value:round];
        b=[read blitCommandEncoder];if(!b)return 2;
        [b copyFromBuffer:gpu sourceOffset:0 toBuffer:output destinationOffset:0 size:bytes];[b synchronizeResource:output];[b endEncoding];
        dispatch_semaphore_t done=dispatch_semaphore_create(0);
        [write addCompletedHandler:^(id<MTLCommandBuffer> c){(void)c;dispatch_semaphore_signal(done);}];
        [read addCompletedHandler:^(id<MTLCommandBuffer> c){(void)c;dispatch_semaphore_signal(done);}];
        [read commit]; // Intentionally enqueue the dependent work first.
        usleep(10000);
        [write commit];
        dispatch_time_t deadline=dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC);
        if(dispatch_semaphore_wait(done,deadline)||dispatch_semaphore_wait(done,deadline)||write.status!=MTLCommandBufferStatusCompleted||read.status!=MTLCommandBufferStatusCompleted){emit(@{@"phase":@"error",@"round":@(round),@"write_error":write.error.description?:@"none",@"read_error":read.error.description?:@"none"});return 3;}
        [write waitUntilCompleted];[read waitUntilCompleted];
        uint64_t bad=0;for(uint32_t i=0;i<words;i++)if(((const uint32_t*)output.contents)[i]!=value(i,round))bad++;
        emit(@{@"phase":@"round",@"round":@(round),@"bad":@(bad),@"event_value":@(event.signaledValue)});
        if(bad||event.signaledValue<round)return 4;
    }}
    emit(@{@"phase":@"done",@"passed":@YES,@"rounds":@32,@"values_checked":@(32ULL*1024*1024),@"pid":@(getpid())});return 0;
}}
