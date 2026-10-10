// Opt-in native QEMU framebuffer; the Raphael iGPU remains the Metal device.
#ifndef KERNEL
#define KERNEL 1
#endif
#include <IOKit/graphics/IOFramebuffer.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOCommandGate.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include "ConsoleFramebufferPolicy.hpp"

static uint64_t fbNS() { uint64_t t=0,n=0;clock_get_uptime(&t);absolutetime_to_nanoseconds(t,&n);return n; }
class RaphaelFramebuffer : public IOFramebuffer {
    OSDeclareDefaultStructors(RaphaelFramebuffer)
    IOPCIDevice *pci=nullptr;
    IOMemoryDescriptor *pixels=nullptr;
    IOMemoryMap *registers=nullptr;
    IOWorkLoop *loop=nullptr;
    IOCommandGate *gate=nullptr;
    IOTimerEventSource *timer=nullptr;
    IOFBInterruptProc callback=nullptr;
    OSObject *target=nullptr;
    void *reference=nullptr;
    bool enabled=false,online=true,stopping=false,superStarted=false,gateAdded=false,timerAdded=false;
    uint64_t armGeneration=0,interruptGeneration=0;
    void *interruptHandle=nullptr;
    uint32_t current=3,available=0;
    uint64_t transportBytes=0,vblCount=0;
    RaphaelFB::Cadence cadence;
    enum Operation { Register,Unregister,Enable,Mode,Power,Stop };
    struct Request { Operation op; IOFBInterruptProc proc=nullptr; OSObject *target=nullptr; void *ref=nullptr; void **out=nullptr; void *handle=nullptr; uint32_t value=0; };
    static IOReturn action(OSObject *owner,void *a,void *,void *,void *);
    static void tick(OSObject *owner,IOTimerEventSource *);
    void arm() {
        armGeneration++;
        if(!timer || stopping || !enabled || !online || !callback)return;
        uint64_t next=cadence.next(fbNS()),absolute=0;
        if(next){nanoseconds_to_absolutetime(next,&absolute);timer->wakeAtTime(absolute);}
    }
    bool valid(uint32_t id) const { return id && id<=available && pixels; }
    IOReturn request(Request &r) { return gateAdded?gate->runAction(action,&r):kIOReturnNotReady; }
    void teardown();
    bool failStart(){teardown();return false;}
public:
    IOService *probe(IOService *provider,SInt32 *score) override;
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOReturn enableController() override { Request r{Mode};r.value=current;return request(r); }
    bool isConsoleDevice() override { return true; }
    IODeviceMemory *getApertureRange(IOPixelAperture aperture) override {
        if(aperture!=kIOFBSystemAperture || !valid(current))return nullptr;
        auto m=RaphaelFB::modes[current-1];uint64_t bytes=(uint64_t(m.width)*m.height*4+127)&~127ULL;
        if(bytes>pixels->getLength())return nullptr;
        return IODeviceMemory::withRange(pixels->getPhysicalSegment(0,nullptr),bytes);
    }
    const char *getPixelFormats() override { return IO32BitDirectPixels "\0"; }
    IOItemCount getDisplayModeCount() override { return available; }
    IOReturn getDisplayModes(IODisplayModeID *ids) override { if(!ids)return kIOReturnBadArgument;for(uint32_t i=0;i<available;i++)ids[i]=i+1;return kIOReturnSuccess; }
    IOReturn getInformationForDisplayMode(IODisplayModeID id,IODisplayModeInformation *info) override {
        if(!valid(id)||!info)return kIOReturnBadArgument;bzero(info,sizeof(*info));auto m=RaphaelFB::modes[id-1];
        info->nominalWidth=m.width;info->nominalHeight=m.height;info->refreshRate=m.hz<<16;
        info->flags=kDisplayModeValidFlag|kDisplayModeSafeFlag|kDisplayModeAlwaysShowFlag|kDisplayModeBuiltInFlag|kDisplayModeNativeFlag;
        if(id==4)info->flags|=kDisplayModeDefaultFlag;return kIOReturnSuccess;
    }
    UInt64 getPixelFormatsForDisplayMode(IODisplayModeID,IOIndex) override { return 0; }
    IOReturn getPixelInformation(IODisplayModeID id,IOIndex depth,IOPixelAperture aperture,IOPixelInformation *info) override {
        if(!valid(id)||depth||aperture!=kIOFBSystemAperture||!info)return kIOReturnBadArgument;
        bzero(info,sizeof(*info));auto m=RaphaelFB::modes[id-1];info->bytesPerRow=m.width*4;info->bitsPerPixel=32;
        info->pixelType=kIORGBDirectPixels;info->componentCount=3;info->bitsPerComponent=8;
        info->componentMasks[0]=0xff0000;info->componentMasks[1]=0xff00;info->componentMasks[2]=0xff;
        strlcpy(info->pixelFormat,IO32BitDirectPixels,sizeof(info->pixelFormat));info->activeWidth=m.width;info->activeHeight=m.height;return kIOReturnSuccess;
    }
    IOReturn getCurrentDisplayMode(IODisplayModeID *id,IOIndex *depth) override { if(!id||!depth)return kIOReturnBadArgument;*id=current;*depth=0;return kIOReturnSuccess; }
    IOReturn setDisplayMode(IODisplayModeID id,IOIndex depth) override { if(depth||!valid(id))return kIOReturnBadArgument;Request r{Mode};r.value=id;return request(r); }
    IOReturn getTimingInfoForDisplayMode(IODisplayModeID id,IOTimingInformation *info) override {
        if(!valid(id)||!info)return kIOReturnBadArgument;bzero(info,sizeof(*info));auto m=RaphaelFB::modes[id-1];
        info->flags=kIODetailedTimingValid;info->appleTimingID=0;auto &t=info->detailedInfo.v2;
        t.horizontalActive=m.width;t.horizontalBlanking=160;t.horizontalSyncOffset=48;t.horizontalSyncPulseWidth=32;
        t.verticalActive=m.height;t.verticalBlanking=45;t.verticalSyncOffset=3;t.verticalSyncPulseWidth=6;
        t.pixelClock=uint64_t(m.width+160)*(m.height+45)*m.hz;t.minPixelClock=t.maxPixelClock=t.pixelClock;
        return kIOReturnSuccess;
    }
    IOReturn registerForInterruptType(IOSelect type,IOFBInterruptProc proc,OSObject *object,void *ref,void **handle) override {
        if(type!=kIOFBVBLInterruptType)return kIOReturnUnsupported;
        Request r{Register};r.proc=proc;r.target=object;r.ref=ref;r.out=handle;return request(r);
    }
    IOReturn unregisterInterrupt(void *handle) override { Request r{Unregister};r.handle=handle;return request(r); }
    IOReturn setInterruptState(void *handle,UInt32 state) override { if(state>1)return kIOReturnBadArgument;Request r{Enable};r.handle=handle;r.value=state;return request(r); }
    IOReturn setAttribute(IOSelect attribute,uintptr_t value) override {
        if(attribute==kIOPowerAttribute){Request r{Power};r.value=value?1:0;return request(r);}
        return IOFramebuffer::setAttribute(attribute,value);
    }
};
OSDefineMetaClassAndStructors(RaphaelFramebuffer,IOFramebuffer)

IOService *RaphaelFramebuffer::probe(IOService *provider,SInt32 *score) {
    uint32_t opt=0;if(!PE_parse_boot_argn("rgpunativefb",&opt,sizeof(opt))||opt!=1)return nullptr;
    auto device=OSDynamicCast(IOPCIDevice,provider);
    if(!device||device->configRead32(0)!=0x11111234||(device->configRead32(8)>>8)!=0x038000||device->configRead32(0x2c)!=0x11001af4)return nullptr;
    return IOFramebuffer::probe(provider,score);
}
bool RaphaelFramebuffer::start(IOService *provider) {
    pci=OSDynamicCast(IOPCIDevice,provider);if(!pci)return false;
    pixels=pci->getDeviceMemoryWithRegister(kIOPCIConfigBaseAddress0);
    if(!pixels||pixels->getLength()!=64ULL*1024*1024){pixels=nullptr;return false;}pixels->retain();pci->setMemoryEnable(true);
    registers=pci->mapDeviceMemoryWithRegister(kIOPCIConfigBaseAddress2);
    if(!registers||registers->getLength()!=4096)return failStart();
    volatile uint16_t *vbe=(volatile uint16_t *)(registers->getVirtualAddress()+0x500);
    volatile uint32_t *snapshot=(volatile uint32_t *)(registers->getVirtualAddress()+0x700);
    if(vbe[0]!=0xb0c5 || snapshot[0]!=0x52534732 || (snapshot[1]!=32U*1024*1024&&snapshot[1]!=64U*1024*1024))return failStart();
    transportBytes=snapshot[1];for(size_t i=0;i<RaphaelFB::count;i++){if(!RaphaelFB::fits(RaphaelFB::modes[i],pixels->getLength(),transportBytes))break;available++;}
    if(available<8)return failStart();
    loop=IOWorkLoop::workLoop();gate=IOCommandGate::commandGate(this);timer=IOTimerEventSource::timerEventSource(this,tick);
    if(!loop||!gate||!timer)return failStart();
    if(loop->addEventSource(gate)!=kIOReturnSuccess)return failStart();gateAdded=true;
    if(loop->addEventSource(timer)!=kIOReturnSuccess)return failStart();timerAdded=true;
    setProperty("IOFBDependentID",pci->getRegistryEntryID(),64);setProperty("IOFBDependentIndex",uint64_t(0),32);
    setProperty("RaphaelNativeFramebuffer",true);setProperty("SyntheticVBL",true);setProperty("NativeModeCount",available,32);
    superStarted=IOFramebuffer::start(provider);if(!superStarted){teardown();return false;}
    setProperty("NativeConsoleReady",true);
    IOLog("RaphaelFramebuffer: native modes=%u software VBL ready\n",available);return true;
}
IOReturn RaphaelFramebuffer::action(OSObject *owner,void *a,void *,void *,void *) {
    auto self=OSDynamicCast(RaphaelFramebuffer,owner);auto r=(Request *)a;if(!self||!r)return kIOReturnBadArgument;
    if(self->stopping&&r->op!=Stop&&r->op!=Unregister)return kIOReturnNotReady;
    switch(r->op){
    case Register:
        if(!r->proc||!r->target||!r->out)return kIOReturnBadArgument;if(self->callback)return kIOReturnExclusiveAccess;
        if(self->interruptGeneration==UINT64_MAX)return kIOReturnNoResources;
        self->interruptHandle=reinterpret_cast<void *>(uintptr_t(++self->interruptGeneration));
        r->target->retain();self->callback=r->proc;self->target=r->target;self->reference=r->ref;*r->out=self->interruptHandle;return kIOReturnSuccess;
    case Unregister:
        if(r->handle!=self->interruptHandle || !self->callback)return kIOReturnBadArgument;
        self->enabled=false;self->timer->cancelTimeout();self->callback=nullptr;self->reference=nullptr;self->interruptHandle=nullptr;
        OSSafeReleaseNULL(self->target);return kIOReturnSuccess;
    case Enable:
        if(r->handle!=self->interruptHandle||!self->callback)return kIOReturnBadArgument;
        self->enabled=r->value;self->timer->cancelTimeout();self->cadence.reset(fbNS(),RaphaelFB::modes[self->current-1].hz);self->arm();return kIOReturnSuccess;
    case Mode:{
        if(!self->valid(r->value)||!self->registers)return kIOReturnBadArgument;auto m=RaphaelFB::modes[r->value-1];
        volatile uint16_t *vbe=(volatile uint16_t *)(self->registers->getVirtualAddress()+0x500);
        vbe[4]=0;vbe[1]=m.width;vbe[2]=m.height;vbe[3]=32;vbe[6]=m.width;vbe[7]=m.height;vbe[8]=0;vbe[9]=0;vbe[4]=0x41;
        if(vbe[1]!=m.width||vbe[2]!=m.height||vbe[3]!=32||vbe[4]!=0x41)return kIOReturnIOError;
        self->current=r->value;self->timer->cancelTimeout();self->cadence.reset(fbNS(),m.hz);self->arm();
        self->setProperty("NativeRefresh",m.hz,32);IOLog("RaphaelFramebuffer: mode=%ux%u hz=%u\n",m.width,m.height,m.hz);return kIOReturnSuccess;}
    case Power:self->online=r->value;self->timer->cancelTimeout();self->cadence.reset(fbNS(),RaphaelFB::modes[self->current-1].hz);self->arm();return kIOReturnSuccess;
    case Stop:self->stopping=true;self->enabled=false;if(self->timer)self->timer->cancelTimeout();return kIOReturnSuccess;
    }
    return kIOReturnBadArgument;
}
void RaphaelFramebuffer::tick(OSObject *owner,IOTimerEventSource *) {
    auto self=OSDynamicCast(RaphaelFramebuffer,owner);if(!self||self->stopping||!self->online||!self->enabled||!self->callback)return;
    uint64_t generation=self->armGeneration;
    self->vblCount++;self->callback(self->target,self->reference);
    // handleVBL may reenter setInterruptState and already schedule the timer.
    if(self->armGeneration==generation)self->arm();
}
void RaphaelFramebuffer::teardown(){
    if(gateAdded){Request r{Stop};request(r);}else{stopping=true;enabled=false;}
    if(timer){timer->cancelTimeout();timer->disable();if(timerAdded){loop->removeEventSource(timer);timerAdded=false;}OSSafeReleaseNULL(timer);}
    if(gate){if(gateAdded){loop->removeEventSource(gate);gateAdded=false;}OSSafeReleaseNULL(gate);}OSSafeReleaseNULL(loop);
    callback=nullptr;reference=nullptr;interruptHandle=nullptr;OSSafeReleaseNULL(target);
    OSSafeReleaseNULL(registers);OSSafeReleaseNULL(pixels);pci=nullptr;available=0;transportBytes=0;
}
void RaphaelFramebuffer::stop(IOService *provider){if(gateAdded){Request r{Stop};request(r);}if(superStarted){IOFramebuffer::stop(provider);superStarted=false;}teardown();}
void RaphaelFramebuffer::free(){teardown();IOFramebuffer::free();}
