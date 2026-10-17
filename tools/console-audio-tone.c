// Own CPU-generated output only; no capture, input device or default-route writes.
// clang -std=c11 -O2 console-audio-tone.c -framework AudioToolbox -framework CoreAudio -framework CoreFoundation -o console-audio-tone
#include <AudioToolbox/AudioToolbox.h>
#include <CoreAudio/CoreAudio.h>
#include <CoreFoundation/CoreFoundation.h>
#include <math.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static atomic_ullong frames;
static atomic_int format_error;
static double rate;
static AudioObjectPropertyAddress addr(AudioObjectPropertySelector selector, AudioObjectPropertyScope scope) {
    AudioObjectPropertyAddress a={selector,scope,kAudioObjectPropertyElementMain};return a;
}
static void check(OSStatus s,const char *where){if(s!=noErr){fprintf(stderr,"%s: %d\n",where,(int)s);exit(2);}}
static void text(AudioDeviceID id,AudioObjectPropertySelector selector,char *out,size_t size){
    CFStringRef value=NULL;UInt32 n=sizeof(value);AudioObjectPropertyAddress a=addr(selector,kAudioObjectPropertyScopeGlobal);
    check(AudioObjectGetPropertyData(id,&a,0,NULL,&n,&value),"device text");
    if(!value || !CFStringGetCString(value,out,size,kCFStringEncodingUTF8)){fprintf(stderr,"device string unavailable\n");exit(2);}CFRelease(value);
}
static unsigned channels(AudioDeviceID id){
    AudioObjectPropertyAddress a=addr(kAudioDevicePropertyStreamConfiguration,kAudioObjectPropertyScopeOutput);UInt32 size=0;
    check(AudioObjectGetPropertyDataSize(id,&a,0,NULL,&size),"output configuration size");
    AudioBufferList *b=calloc(1,size);if(!b)exit(2);check(AudioObjectGetPropertyData(id,&a,0,NULL,&size,b),"output configuration");
    unsigned count=0;for(UInt32 i=0;i<b->mNumberBuffers;i++)count+=b->mBuffers[i].mNumberChannels;free(b);return count;
}
static AudioDeviceID default_device(AudioObjectPropertySelector selector){
    AudioDeviceID id=0;UInt32 n=sizeof(id);AudioObjectPropertyAddress a=addr(selector,kAudioObjectPropertyScopeGlobal);
    check(AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,NULL,&n,&id),"default read");return id;
}
static OSStatus render(void *ref,AudioUnitRenderActionFlags *flags,const AudioTimeStamp *time,UInt32 bus,UInt32 n,AudioBufferList *data){
    (void)ref;(void)flags;(void)time;(void)bus;
    if(data->mNumberBuffers!=1 || data->mBuffers[0].mNumberChannels!=2 || data->mBuffers[0].mDataByteSize<n*2*sizeof(float) || !data->mBuffers[0].mData){
        atomic_store(&format_error,1);for(UInt32 b=0;b<data->mNumberBuffers;b++)if(data->mBuffers[b].mData)memset(data->mBuffers[b].mData,0,data->mBuffers[b].mDataByteSize);return noErr;
    }
    float *out=data->mBuffers[0].mData;unsigned long long first=atomic_load(&frames);
    for(UInt32 i=0;i<n;i++){
        double t=(first+i)/rate,start=0,end=0;int left=0,right=0;
        if(t>=1 && t<2){start=1;end=2;left=1;}
        else if(t>=2.5 && t<3.5){start=2.5;end=3.5;right=1;}
        else if(t>=4 && t<5){start=4;end=5;left=right=1;}
        double ramp=(left||right)?fmin(1,fmin((t-start)/.005,(end-t)/.005)):0;
        out[2*i]=(float)(left*.02*ramp*sin(2*3.141592653589793*997*t));
        out[2*i+1]=(float)(right*.02*ramp*sin(2*3.141592653589793*1499*t));
    }
    atomic_store(&frames,first+n);return noErr;
}
int main(int argc,char **argv){
    if(argc!=2 && !(argc==3 && !strcmp(argv[1],"--uid"))){fprintf(stderr,"usage: console-audio-tone --list | --uid EXACT_UID\n");return 2;}
    int list=argc==2 && !strcmp(argv[1],"--list");if(argc==2 && !list)return 2;
    alarm(12);
    AudioObjectPropertyAddress a=addr(kAudioHardwarePropertyDevices,kAudioObjectPropertyScopeGlobal);UInt32 bytes=0;
    check(AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,&a,0,NULL,&bytes),"device count");
    AudioDeviceID *ids=malloc(bytes);if(!ids)return 2;check(AudioObjectGetPropertyData(kAudioObjectSystemObject,&a,0,NULL,&bytes,ids),"devices");
    AudioDeviceID chosen=0;unsigned matches=0;
    for(unsigned i=0;i<bytes/sizeof(*ids);i++){
        char uid[1024],maker[512];text(ids[i],kAudioDevicePropertyDeviceUID,uid,sizeof(uid));text(ids[i],kAudioObjectPropertyManufacturer,maker,sizeof(maker));
        UInt32 transport=0,n=sizeof(transport);a=addr(kAudioDevicePropertyTransportType,kAudioObjectPropertyScopeGlobal);
        check(AudioObjectGetPropertyData(ids[i],&a,0,NULL,&n,&transport),"transport");unsigned count=channels(ids[i]);
        if(list)printf("%u\t%s\t%s\ttransport=%08x\toutputs=%u\n",ids[i],uid,maker,transport,count);
        else if(!strcmp(uid,argv[2]) && strstr(maker,"QEMU") && transport==kAudioDeviceTransportTypeUSB && count==2){chosen=ids[i];matches++;}
    }
    free(ids);if(list)return 0;if(matches!=1){fprintf(stderr,"need exactly one matching stereo QEMU USB output\n");return 2;}
    AudioDeviceID prior=default_device(kAudioHardwarePropertyDefaultOutputDevice),prior_system=default_device(kAudioHardwarePropertyDefaultSystemOutputDevice);
    UInt32 n=sizeof(rate);a=addr(kAudioDevicePropertyNominalSampleRate,kAudioObjectPropertyScopeGlobal);check(AudioObjectGetPropertyData(chosen,&a,0,NULL,&n,&rate),"sample rate");
    if(!isfinite(rate) || rate<32000 || rate>192000)return 2;
    AudioComponentDescription desc={kAudioUnitType_Output,kAudioUnitSubType_HALOutput,kAudioUnitManufacturer_Apple,0,0};
    AudioComponent component=AudioComponentFindNext(NULL,&desc);if(!component)return 2;AudioUnit unit=NULL;check(AudioComponentInstanceNew(component,&unit),"create HAL");
    UInt32 disabled=0;check(AudioUnitSetProperty(unit,kAudioOutputUnitProperty_EnableIO,kAudioUnitScope_Input,1,&disabled,sizeof(disabled)),"disable input");
    check(AudioUnitSetProperty(unit,kAudioOutputUnitProperty_CurrentDevice,kAudioUnitScope_Global,0,&chosen,sizeof(chosen)),"exact output device");
    AudioStreamBasicDescription format={rate,kAudioFormatLinearPCM,kAudioFormatFlagsNativeFloatPacked,8,1,8,2,32,0};
    check(AudioUnitSetProperty(unit,kAudioUnitProperty_StreamFormat,kAudioUnitScope_Input,0,&format,sizeof(format)),"client stereo format");
    AURenderCallbackStruct cb={render,NULL};check(AudioUnitSetProperty(unit,kAudioUnitProperty_SetRenderCallback,kAudioUnitScope_Input,0,&cb,sizeof(cb)),"callback");
    check(AudioUnitInitialize(unit),"initialize");check(AudioOutputUnitStart(unit),"start");
    while(atomic_load(&frames)<(unsigned long long)(6*rate) && !atomic_load(&format_error))usleep(10000);
    check(AudioOutputUnitStop(unit),"stop");check(AudioUnitUninitialize(unit),"uninitialize");check(AudioComponentInstanceDispose(unit),"dispose");
    int unchanged=prior==default_device(kAudioHardwarePropertyDefaultOutputDevice) && prior_system==default_device(kAudioHardwarePropertyDefaultSystemOutputDevice);
    printf("{\"device_id\":%u,\"rate\":%.0f,\"frames\":%llu,\"peak\":0.02,\"defaults_unchanged\":%s,\"format_error\":%d}\n",chosen,rate,atomic_load(&frames),unchanged?"true":"false",atomic_load(&format_error));
    return unchanged && !atomic_load(&format_error)?0:3;
}
