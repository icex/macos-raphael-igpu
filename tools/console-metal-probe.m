// Independent Metal-to-QEMU presentation check. Generates its own pixels; no desktop capture.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOKit/IOKitLib.h>
#include <unistd.h>
#include <string.h>
int main(void) { @autoreleasepool {
    id<MTLDevice> gpu=MTLCreateSystemDefaultDevice();
    if(!gpu)return 2;
    NSError *error=nil;
    NSString *source=@"#include <metal_stdlib>\nusing namespace metal;\nkernel void bars(device uint *p [[buffer(0)]],constant uint &phase [[buffer(1)]],uint i [[thread_position_in_grid]]) { if(i>=1280*720)return; uint colors[3]={0xffff0000u,0xff00ff00u,0xff0000ffu}; p[i]=colors[((i%1280)*3/1280+phase)%3]; }";
    id<MTLLibrary> lib=[gpu newLibraryWithSource:source options:nil error:&error];
    id<MTLComputePipelineState> pipeline=lib?[gpu newComputePipelineStateWithFunction:[lib newFunctionWithName:@"bars"] error:&error]:nil;
    if(!pipeline){fprintf(stderr,"shader: %s\n",error.description.UTF8String);return 2;}
    const NSUInteger bytes=1280*720*4;
    id<MTLBuffer> pixels=[gpu newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    id<MTLCommandQueue> queue=[gpu newCommandQueue];
    if(!pixels||!queue)return 2;
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("RaphaelConsole"));
    if(!service)return 3;
    io_connect_t client=IO_OBJECT_NULL;
    kern_return_t kr=IOServiceOpen(service,mach_task_self(),0,&client);IOObjectRelease(service);
    if(kr)return 3;
    mach_vm_address_t address=0;mach_vm_size_t size=0;
    kr=IOConnectMapMemory64(client,0,mach_task_self(),&address,&size,kIOMapAnywhere);
    if(kr||size<bytes){IOServiceClose(client);return 3;}
    uint64_t dims[]={1280,720};
    kr=IOConnectCallScalarMethod(client,0,dims,2,NULL,NULL);
    int result=kr?3:0;
    for(unsigned phase=0;!result&&phase<3;phase++) {
        id<MTLCommandBuffer> command=[queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder=[command computeCommandEncoder];
        [encoder setComputePipelineState:pipeline];[encoder setBuffer:pixels offset:0 atIndex:0];
        [encoder setBytes:&phase length:sizeof(phase) atIndex:1];
        [encoder dispatchThreads:MTLSizeMake(1280*720,1,1) threadsPerThreadgroup:MTLSizeMake(pipeline.threadExecutionWidth,1,1)];
        [encoder endEncoding];[command commit];[command waitUntilCompleted];
        if(command.status!=MTLCommandBufferStatusCompleted){result=4;break;}
        const uint32_t colors[]={0xffff0000,0xff00ff00,0xff0000ff};
        const uint32_t *actual=pixels.contents;
        for(unsigned i=0;i<1280*720;i++)if(actual[i]!=colors[((i%1280)*3/1280+phase)%3]){result=5;break;}
        if(result)break;
        memcpy((void *)address,actual,bytes);
        printf("CONSOLE_METAL phase=%u verified_pixels=921600 device=%s registry=%llu\n",phase,gpu.name.UTF8String,gpu.registryID);fflush(stdout);
        sleep(15);
    }
    IOConnectUnmapMemory64(client,0,mach_task_self(),address);IOServiceClose(client);
    printf("CONSOLE_METAL exit=%d\n",result);return result;
}}
