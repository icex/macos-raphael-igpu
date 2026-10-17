// Read-only samples from the exact accelerator, without creating a Metal client.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <unistd.h>
int main(int argc,const char **argv) { @autoreleasepool {
    uint64_t wanted=argc>1?strtoull(argv[1],NULL,0):0;
    io_registry_entry_t service=IOServiceGetMatchingService(kIOMainPortDefault,IORegistryEntryIDMatching(wanted));
    if(!service)return 2;
    for(unsigned i=0;i<20;i++) { @autoreleasepool {
        CFTypeRef raw=IORegistryEntryCreateCFProperty(service,CFSTR("PerformanceStatistics"),kCFAllocatorDefault,0);
        if(!raw||CFGetTypeID(raw)!=CFDictionaryGetTypeID()){if(raw)CFRelease(raw);IOObjectRelease(service);return 3;}
        NSDictionary *d=CFBridgingRelease(raw);NSMutableDictionary *out=[@{@"sample":@(i),@"registry_id":@(wanted),@"epoch":@([NSDate date].timeIntervalSince1970)} mutableCopy];
        for(NSString *k in @[@"vramFreeBytes",@"inUseVidMemoryBytes",@"inUseSysMemoryBytes",@"gartUsedBytes",@"gartFreeBytes",@"gartCacheBytes",@"orphanedReusableVidMemoryBytes",@"orphanedNonReusableVidMemoryBytes",@"orphanedNonReusableSysMemoryBytes",@"textureCount",@"surfaceCount",@"clientSharedAllocatedBytes"])if([d[k] isKindOfClass:NSNumber.class])out[k]=d[k];
        NSData *j=[NSJSONSerialization dataWithJSONObject:out options:0 error:nil];fwrite(j.bytes,1,j.length,stdout);putchar('\n');fflush(stdout);
        usleep(500000);
    }}
    IOObjectRelease(service);return 0;
}}
