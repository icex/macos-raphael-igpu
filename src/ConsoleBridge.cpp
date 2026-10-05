// Optional presentation-only bridge to QEMU's Bochs display console.
// Raphael remains the rendering device. No DMA or physical-GPU mappings here.
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

class RaphaelConsole : public IOService {
    OSDeclareDefaultStructors(RaphaelConsole)
    IOPCIDevice *pci = nullptr;
    IOMemoryMap *registers = nullptr;
    IOMemoryDescriptor *pixels = nullptr;
    IOLock *lock = nullptr;
public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOReturn newUserClient(task_t task, void *securityID, UInt32 type,
                          OSDictionary *properties, IOUserClient **handler) override;
    IOReturn mode(uint64_t width, uint64_t height);
    IOMemoryDescriptor *framebuffer() { return pixels; }
};
class RaphaelConsoleClient : public IOUserClient {
    OSDeclareDefaultStructors(RaphaelConsoleClient)
    RaphaelConsole *console = nullptr;
public:
    bool start(IOService *provider) override {
        console = OSDynamicCast(RaphaelConsole, provider);
        if (!console || !IOUserClient::start(provider)) return false;
        return console->open(this);
    }
    IOReturn clientClose() override {
        if (console && console->isOpen(this)) console->close(this);
        terminate(); return kIOReturnSuccess;
    }
    void stop(IOService *provider) override {
        if (console && console->isOpen(this)) console->close(this);
        console = nullptr; IOUserClient::stop(provider);
    }
    IOReturn clientMemoryForType(UInt32 type, IOOptionBits *options,
                                 IOMemoryDescriptor **memory) override {
        if (type || !console || isInactive()) return kIOReturnBadArgument;
        *memory = console->framebuffer();
        if (!*memory) return kIOReturnNotReady;
        (*memory)->retain(); *options = 0; return kIOReturnSuccess;
    }
    IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
                           IOExternalMethodDispatch *, OSObject *, void *) override {
        if (!console || isInactive()) return kIOReturnNotReady;
        if (selector || args->scalarInputCount != 2 || args->structureInputSize ||
            args->structureInputDescriptor || args->scalarOutputCount ||
            args->structureOutputSize || args->structureOutputDescriptor)
            return kIOReturnBadArgument;
        return console->mode(args->scalarInput[0], args->scalarInput[1]);
    }
};
OSDefineMetaClassAndStructors(RaphaelConsole, IOService)
OSDefineMetaClassAndStructors(RaphaelConsoleClient, IOUserClient)

bool RaphaelConsole::start(IOService *provider) {
    uint32_t enabled = 0;
    if (!PE_parse_boot_argn("rgpuconsole", &enabled, sizeof(enabled)) || enabled != 1)
        return false;
    pci = OSDynamicCast(IOPCIDevice, provider);
    if (!pci || pci->configRead32(0) != 0x11111234 ||
        (pci->configRead32(8) >> 8) != 0x038000 || !IOService::start(provider))
        return false;
    pixels = pci->getDeviceMemoryWithRegister(kIOPCIConfigBaseAddress0);
    if (!pixels || pixels->getLength() < 16*1024*1024 ||
        pixels->getLength() > 64*1024*1024) { pixels = nullptr; return false; }
    pixels->retain();
    pci->setMemoryEnable(true);
    registers = pci->mapDeviceMemoryWithRegister(kIOPCIConfigBaseAddress2);
    lock = IOLockAlloc();
    if (!registers || registers->getLength() != 4096 || !lock) return false;
    volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
    if (vbe[0] != 0xb0c5) return false;
    setProperty("PresentationOnly", true);
    setProperty("ConsoleProtocol", 1, 32);
    registerService();
    IOLog("RaphaelConsole: Bochs presentation bridge ready, no DMA\n");
    return true;
}
IOReturn RaphaelConsole::mode(uint64_t width, uint64_t height) {
    if (width < 320 || height < 200 || width > 4096 || height > 2304 ||
        !pixels || width * height * 4 > pixels->getLength()) return kIOReturnBadArgument;
    IOLockLock(lock);
    if (isInactive() || !registers) { IOLockUnlock(lock); return kIOReturnNotReady; }
    volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
    vbe[4]=0; OSSynchronizeIO();
    vbe[1]=width; vbe[2]=height; vbe[3]=32; vbe[6]=width; vbe[8]=0; vbe[9]=0;
    OSSynchronizeIO(); vbe[4]=0x41; OSSynchronizeIO();
    const bool matched = vbe[1]==width && vbe[2]==height && vbe[3]==32 && vbe[4]==0x41;
    IOLockUnlock(lock);
    return matched ? kIOReturnSuccess : kIOReturnIOError;
}
IOReturn RaphaelConsole::newUserClient(task_t task, void *securityID, UInt32 type,
                                       OSDictionary *properties, IOUserClient **handler) {
    if (type || isInactive() || IOUserClient::clientHasPrivilege(securityID, kIOClientPrivilegeLocalUser)
                              != kIOReturnSuccess) return kIOReturnNotPrivileged;
    auto *client = new RaphaelConsoleClient;
    if (!client) return kIOReturnNoMemory;
    if (!client->initWithTask(task, securityID, type, properties)) {
        client->release(); return kIOReturnError;
    }
    if (!client->attach(this)) { client->release(); return kIOReturnError; }
    if (!client->start(this)) { client->detach(this); client->release(); return kIOReturnExclusiveAccess; }
    *handler = client; return kIOReturnSuccess;
}
void RaphaelConsole::stop(IOService *provider) {
    if (lock) IOLockLock(lock);
    if (registers) {
        volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
        vbe[4]=0; OSSynchronizeIO();
    }
    if (lock) IOLockUnlock(lock);
    IOService::stop(provider);
}
void RaphaelConsole::free() {
    if (registers) { registers->release(); registers=nullptr; }
    if (pixels) { pixels->release(); pixels=nullptr; }
    if (lock) { IOLockFree(lock); lock=nullptr; }
    IOService::free();
}
