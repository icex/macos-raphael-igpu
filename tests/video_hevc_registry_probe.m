// Read-only reproduction of AppleGVA's HEVC capability searches.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOKit/IOKitLib.h>
#include <signal.h>
#include <unistd.h>
#include <dlfcn.h>
@interface NSObject (RGPUService)
- (io_service_t)ioService;
@end
static void emit(NSDictionary *d) {
    NSData *b=[NSJSONSerialization dataWithJSONObject:d options:0 error:NULL];
    fwrite(b.bytes,1,b.length,stdout); puts(""); fflush(stdout);
}
static void inspect(io_registry_entry_t s, NSString *origin) {
    io_name_t name={0}; io_string_t path={0}; uint64_t rid=0;
    kern_return_t nr=IORegistryEntryGetNameInPlane(s,kIOServicePlane,name);
    kern_return_t pr=IORegistryEntryGetPath(s,kIOServicePlane,path);
    kern_return_t ir=IORegistryEntryGetRegistryEntryID(s,&rid);
    NSMutableDictionary *d=[@{@"phase":@"registry",@"origin":origin,@"service":@(s),
        @"name":@(name),@"path":@(path),@"registry_id":@(rid),
        @"name_status":@(nr),@"path_status":@(pr),@"id_status":@(ir)} mutableCopy];
    for (NSString *key in @[@"IOGVAHEVCDecode",@"IOGVAHEVCDecodeCapabilities",@"IOGVACodec"]) {
        NSMutableDictionary *values=[NSMutableDictionary dictionary];
        for (NSNumber *opt in @[@0,@1,@3]) {
            CFTypeRef v=IORegistryEntrySearchCFProperty(s,kIOServicePlane,(__bridge CFStringRef)key,kCFAllocatorDefault,opt.unsignedIntValue);
            values[opt.stringValue]=v ? @{@"type":@(CFGetTypeID(v)),@"value":[(__bridge id)v description]} : (id)[NSNull null];
            if(v)CFRelease(v);
        }
        d[key]=values;
    }
    emit(d);
}
int main(void) {
    @autoreleasepool {
        alarm(60); setbuf(stdout,NULL);
        io_iterator_t it=0; kern_return_t kr=IORegistryCreateIterator(kIOMainPortDefault,kIOServicePlane,kIORegistryIterateRecursively,&it);
        emit(@{@"phase":@"iterator",@"status":@(kr)});
        if(kr)return 1;
        io_registry_entry_t s;
        while((s=IOIteratorNext(it))) {
            io_name_t name={0}; IORegistryEntryGetNameInPlane(s,kIOServicePlane,name);
            if(!strncmp(name,"GFX0",4)||!strncmp(name,"IOPP",4)||!strncmp(name,"IGPU",4)||!strncmp(name,"display",7))
                inspect(s,@"AppleGVA-name-search");
            IOObjectRelease(s);
        }
        IOObjectRelease(it);
        NSArray<id<MTLDevice>> *devices=MTLCopyAllDevices();
        void *vt=dlopen("/System/Library/Frameworks/VideoToolbox.framework/VideoToolbox",RTLD_NOW);
        typedef Boolean (*Classify)(uint64_t);
        Classify slotted=(Classify)(vt ? dlsym(vt,"VTIsMetalDeviceSlotted") : NULL);
        Classify external=(Classify)(vt ? dlsym(vt,"VTIsMetalDeviceExternal") : NULL);
        emit(@{@"phase":@"metal-count",@"count":@(devices.count)});
        for(id<MTLDevice> device in devices) {
            emit(@{@"phase":@"metal-device",@"name":device.name,@"registry_id":@(device.registryID)});
            emit(@{@"phase":@"vt-device-classification",@"slotted":slotted ? @(slotted(device.registryID)) : (id)[NSNull null],
                @"external":external ? @(external(device.registryID)) : (id)[NSNull null]});
            s=IOServiceGetMatchingService(kIOMainPortDefault,IORegistryEntryIDMatching(device.registryID));
            if(s){inspect(s,@"Metal-registryID-match");IOObjectRelease(s);}
            if([(id)device respondsToSelector:@selector(ioService)]) {
                s=[(id)device ioService];
                if(s)inspect(s,@"Metal-ioService");
            }
        }
        typedef int32_t (*CopyDecoders)(CFDictionaryRef,CFArrayRef *);
        CopyDecoders copy=(CopyDecoders)(vt ? dlsym(vt,"VTCopyVideoDecoderList") : NULL);
        if(copy) {
            CFArrayRef list=NULL; int32_t status=copy(NULL,&list);
            emit(@{@"phase":@"decoder-list",@"status":@(status),@"entries":list ? [(__bridge NSArray *)list description] : @""});
            if(list)CFRelease(list);
        }
        if(vt)dlclose(vt);
        return 0;
    }
}
