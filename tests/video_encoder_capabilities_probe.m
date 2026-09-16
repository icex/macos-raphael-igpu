// Read-only session/property investigation; submits no frames. Supervised use.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#include <signal.h>
#include <unistd.h>
static void expired(int sig) { (void)sig; _exit(124); }
static void emit(NSString *phase,NSDictionary *fields) {
    NSMutableDictionary *d=[fields mutableCopy]; d[@"phase"]=phase;
    NSData *j=[NSJSONSerialization dataWithJSONObject:d options:0 error:NULL];
    fwrite(j.bytes,1,j.length,stdout); puts(""); fflush(stdout);
}
int main(int argc,const char **argv) { @autoreleasepool {
    signal(SIGALRM,expired); alarm(30); if(argc!=2) return 2;
    uint64_t registry=strtoull(argv[1],NULL,0); if(!registry) return 2;
    for(NSNumber *format in @[@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange),@(kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange)]) {
        NSDictionary *spec=@{(__bridge id)kVTVideoEncoderSpecification_EnableHardwareAcceleratedVideoEncoder:@YES,
          (__bridge id)kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder:@YES,
          (__bridge id)kVTVideoEncoderSpecification_RequiredEncoderGPURegistryID:@(registry)};
        NSDictionary *attrs=@{(__bridge id)kCVPixelBufferPixelFormatTypeKey:format,
          (__bridge id)kCVPixelBufferWidthKey:@1280,(__bridge id)kCVPixelBufferHeightKey:@720,
          (__bridge id)kCVPixelBufferIOSurfacePropertiesKey:@{}};
        VTCompressionSessionRef s=NULL;
        OSStatus status=VTCompressionSessionCreate(NULL,1280,720,kCMVideoCodecType_HEVC,(__bridge CFDictionaryRef)spec,
                                                  (__bridge CFDictionaryRef)attrs,NULL,NULL,NULL,&s);
        emit(@"create",@{@"pixel_format":format,@"status":@(status)});
        if(status || !s) return 1;
        CFDictionaryRef props=NULL; status=VTSessionCopySupportedPropertyDictionary(s,&props);
        NSDictionary *profile=props ? ((__bridge NSDictionary *)props)[(__bridge id)kVTCompressionPropertyKey_ProfileLevel] : nil;
        emit(@"supported-profile",@{@"status":@(status),@"entry":profile ? [profile description] : @"absent"});
        if(props) CFRelease(props);
        CFTypeRef idValue=NULL; status=VTSessionCopyProperty(s,kVTCompressionPropertyKey_EncoderID,NULL,&idValue);
        emit(@"encoder-id",@{@"status":@(status),@"value":idValue ? [(__bridge id)idValue description] : @"absent"});
        if(idValue) CFRelease(idValue);
        for(id value in @[(__bridge id)kVTProfileLevel_HEVC_Main_AutoLevel,(__bridge id)kVTProfileLevel_HEVC_Main10_AutoLevel]) {
            status=VTSessionSetProperty(s,kVTCompressionPropertyKey_ProfileLevel,(__bridge CFTypeRef)value);
            emit(@"set-profile",@{@"value":value,@"status":@(status)});
        }
        VTCompressionSessionInvalidate(s); CFRelease(s);
    }
    alarm(0); return 0;
} }
