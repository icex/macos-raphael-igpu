// CPU-checked texture recreation and process-local reclamation; global counters are observations.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurface.h>
#import <IOKit/IOKitLib.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s) { (void)s; _exit(124); }
static void emit(NSDictionary *d) {
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:nil];
    fwrite(j.bytes,1,j.length,stdout); putchar('\n'); fflush(stdout);
}
static uint32_t value(uint32_t i,uint32_t seed) {
    uint32_t x=i^(seed*0x9e3779b9U);x^=x>>16;x*=0x7feb352dU;x^=x>>15;x*=0x846ca68bU;return x^(x>>16);
}
static NSDictionary *stats(io_registry_entry_t service) {
    NSMutableDictionary *out=[NSMutableDictionary new];
    for(NSString *key in @[@"PerformanceStatistics",@"PerformanceStatisticsAccum"]) {
        CFTypeRef raw=IORegistryEntryCreateCFProperty(service,(__bridge CFStringRef)key,kCFAllocatorDefault,0);
        if(!raw) continue;
        id object=CFBridgingRelease(raw);
        if(![object isKindOfClass:NSDictionary.class]) continue;
        NSMutableDictionary *numbers=[NSMutableDictionary new];
        for(NSString *name in object) if([object[name] isKindOfClass:NSNumber.class]) numbers[name]=object[name];
        out[key]=numbers;
    }
    return out;
}
static bool complete(id<MTLCommandBuffer> cb) {
    dispatch_semaphore_t done=dispatch_semaphore_create(0);
    [cb addCompletedHandler:^(id<MTLCommandBuffer> b){(void)b;dispatch_semaphore_signal(done);}];[cb commit];
    if(dispatch_semaphore_wait(done,dispatch_time(DISPATCH_TIME_NOW,20*NSEC_PER_SEC)) || cb.status!=MTLCommandBufferStatusCompleted) {
        emit(@{@"phase":@"error",@"error":cb.error.description?:@"GPU timeout"});return false;
    }
    [cb waitUntilCompleted];return true;
}
static bool one(id<MTLDevice> dev,io_registry_entry_t service,unsigned cycle,unsigned storage,unsigned format,unsigned shape,uint32_t seed,uint64_t *peak) { @autoreleasepool {
    const NSUInteger width=shape?1003:1024,height=shape?769:1024,row=(width*4+255)&~255UL,bytes=row*height;
    id<MTLCommandQueue> uploadQueue=[dev newCommandQueue],readQueue=[dev newCommandQueue];
    id<MTLBuffer> input=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    id<MTLBuffer> output=[dev newBufferWithLength:bytes options:MTLResourceStorageModeManaged];
    MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:format?MTLPixelFormatRGBA8Unorm:MTLPixelFormatBGRA8Unorm width:width height:height mipmapped:NO];
    td.storageMode=storage==0?MTLStorageModePrivate:MTLStorageModeManaged;
    td.usage=MTLTextureUsageShaderRead|MTLTextureUsageRenderTarget;
    id<MTLTexture> texture=nil;
    // ARC retains the IOSurface until the texture/command buffers have completed and the pool drains.
    __attribute__((objc_precise_lifetime)) id surfaceOwner=nil;
    NSUInteger surfaceBytes=0;
    if(storage==2) {
        IOSurfaceRef surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{(id)kIOSurfaceWidth:@(width),(id)kIOSurfaceHeight:@(height),(id)kIOSurfaceBytesPerElement:@4,(id)kIOSurfaceBytesPerRow:@(row),(id)kIOSurfaceAllocSize:@(bytes),(id)kIOSurfacePixelFormat:@(format?0x52474241:0x42475241)});
        if(!surface) return false;
        surfaceBytes=IOSurfaceGetAllocSize(surface);
        texture=[dev newTextureWithDescriptor:td iosurface:surface plane:0];
        surfaceOwner=CFBridgingRelease(surface);
    } else texture=[dev newTextureWithDescriptor:td];
    if(!uploadQueue||!readQueue||!input||!output||!texture) {emit(@{@"phase":@"error",@"error":@"allocation failed",@"storage":@(storage),@"format":@(format)});return false;}
    uint32_t caseSeed=seed+cycle*97+storage*17+format*7+shape;
    memset(input.contents,0x5a,bytes);memset(output.contents,0xa5,bytes);
    for(unsigned y=0;y<height;y++) for(unsigned x=0;x<width;x++) ((uint32_t*)((uint8_t*)input.contents+y*row))[x]=value(y*width+x,caseSeed);
    [input didModifyRange:NSMakeRange(0,bytes)];[output didModifyRange:NSMakeRange(0,bytes)];
    id<MTLCommandBuffer> upload=[uploadQueue commandBuffer];
    id<MTLBlitCommandEncoder> b=[upload blitCommandEncoder];
    if(!upload||!b)return false;
    [b copyFromBuffer:input sourceOffset:0 sourceBytesPerRow:row sourceBytesPerImage:bytes sourceSize:MTLSizeMake(width,height,1) toTexture:texture destinationSlice:0 destinationLevel:0 destinationOrigin:MTLOriginMake(0,0,0)];[b endEncoding];
    // Explicit host completion orders work between two queues; GPU event/fence coverage is separate.
    if(!complete(upload))return false;
    id<MTLCommandBuffer> read=[readQueue commandBuffer];b=[read blitCommandEncoder];
    if(!read||!b)return false;
    [b copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0,0,0) sourceSize:MTLSizeMake(width,height,1) toBuffer:output destinationOffset:0 destinationBytesPerRow:row destinationBytesPerImage:bytes];
    [b synchronizeResource:output];[b endEncoding];if(!complete(read))return false;
    uint64_t bad=0,paddingBad=0;
    for(unsigned y=0;y<height;y++) {
        const uint32_t *p=(const uint32_t*)((const uint8_t*)output.contents+y*row);
        for(unsigned x=0;x<width;x++) if(p[x]!=value(y*width+x,caseSeed)) bad++;
        for(NSUInteger x=width*4;x<row;x++) if(((const uint8_t*)output.contents)[y*row+x]!=0xa5) paddingBad++;
    }
    *peak=dev.currentAllocatedSize;
    emit(@{@"phase":@"case",@"cycle":@(cycle),@"storage":@(storage),@"format":@(format),@"shape":@(shape),@"seed":@(seed),@"pixels":@(width*height),@"bad":@(bad),@"padding_bad":@(paddingBad),@"peak_allocated":@(*peak),@"iosurface_bytes":@(surfaceBytes),@"global":stats(service)});
    return bad==0 && paddingBad==0;
}}
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired);alarm(180);
    uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;uint32_t seed=argc>2?(uint32_t)strtoul(argv[2],NULL,0):1;
    id<MTLDevice> dev=nil;for(id<MTLDevice> d in MTLCopyAllDevices())if(d.registryID==wanted)dev=d;
    if(!dev)return 2;
    io_registry_entry_t service=IOServiceGetMatchingService(kIOMainPortDefault,IORegistryEntryIDMatching(wanted));
    if(!service)return 2;
    uint64_t baseline=dev.currentAllocatedSize,maximumAfter=0,maximumPeak=0,pixels=0;
    const uint64_t tolerance=4*1024*1024;unsigned cases=0;
    emit(@{@"phase":@"begin",@"pid":@(getpid()),@"seed":@(seed),@"registry_id":@(wanted),@"allocated":@(baseline),@"tolerance":@(tolerance),@"global":stats(service)});
    for(unsigned cycle=0;cycle<5;cycle++) {
        for(unsigned storage=0;storage<3;storage++)for(unsigned format=0;format<2;format++)for(unsigned shape=0;shape<2;shape++) {
            uint64_t peak=0;if(!one(dev,service,cycle,storage,format,shape,seed,&peak)){IOObjectRelease(service);return 3;}
            unsigned polls=0;uint64_t after;
            do{usleep(100000);after=dev.currentAllocatedSize;polls++;}while(after>baseline+tolerance&&polls<20);
            emit(@{@"phase":@"released",@"cycle":@(cycle),@"storage":@(storage),@"format":@(format),@"shape":@(shape),@"allocated":@(after),@"baseline":@(baseline),@"polls":@(polls),@"global":stats(service)});
            if(cycle>0) {
                if(after>baseline+tolerance||peak<baseline+4*1024*1024){emit(@{@"phase":@"error",@"error":@"allocation return or pressure gate",@"after":@(after),@"baseline":@(baseline),@"peak":@(peak)});IOObjectRelease(service);return 4;}
                maximumAfter=MAX(maximumAfter,after);maximumPeak=MAX(maximumPeak,peak);pixels+=shape?1003*769:1024*1024;cases++;
            }
        }
        if(cycle==0)baseline=dev.currentAllocatedSize;
    }
    emit(@{@"phase":@"done",@"passed":@YES,@"pid":@(getpid()),@"seed":@(seed),@"cases":@(cases),@"pixels":@(pixels),@"baseline":@(baseline),@"max_after":@(maximumAfter),@"max_peak":@(maximumPeak),@"global":stats(service)});
    IOObjectRelease(service);return 0;
}}
