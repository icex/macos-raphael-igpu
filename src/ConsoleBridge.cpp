// Optional presentation-only bridge to QEMU's Bochs display console.
// Raphael remains the rendering device. No DMA or physical-GPU mappings here.
#ifndef KERNEL
#define KERNEL 1
#endif
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
    IOMemoryDescriptor *staging = nullptr;
    IOUserClient *snapshotOwner = nullptr;
    bool snapshotLeased = false; // Never regrant: mappings may outlive client close.
    bool snapshotAvailable = false;
public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOReturn newUserClient(task_t task, void *securityID, UInt32 type,
                          OSDictionary *properties, IOUserClient **handler) override;
    IOReturn mode(uint64_t width, uint64_t height);
    IOMemoryDescriptor *framebuffer() { return pixels; }
    IOReturn snapshotArm(IOUserClient *owner);
    IOReturn snapshotCommit(IOUserClient *owner, uint64_t w, uint64_t h,
                            uint64_t sequence, uint64_t *ack);
    void snapshotClose(IOUserClient *owner);
    IOMemoryDescriptor *snapshotMemory(IOUserClient *owner) {
        return owner == snapshotOwner ? staging : nullptr;
    }
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
        if (console && console->isOpen(this)) { console->snapshotClose(this); console->close(this); }
        terminate(); return kIOReturnSuccess;
    }
    void stop(IOService *provider) override {
        if (console && console->isOpen(this)) { console->snapshotClose(this); console->close(this); }
        console = nullptr; IOUserClient::stop(provider);
    }
    IOReturn clientMemoryForType(UInt32 type, IOOptionBits *options,
                                 IOMemoryDescriptor **memory) override {
        if (type > 1 || !console || isInactive() || !console->isOpen(this)) return kIOReturnBadArgument;
        *memory = type ? console->snapshotMemory(this) : console->framebuffer();
        if (!*memory) return kIOReturnNotReady;
        (*memory)->retain(); *options = 0; return kIOReturnSuccess;
    }
    IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
                           IOExternalMethodDispatch *, OSObject *, void *) override {
        if (!console || isInactive()) return kIOReturnNotReady;
        if (args->structureInputSize || args->structureInputDescriptor ||
            args->structureOutputSize || args->structureOutputDescriptor)
            return kIOReturnBadArgument;
        if (!console->isOpen(this)) return kIOReturnExclusiveAccess;
        if (selector == 0 && args->scalarInputCount == 2 && !args->scalarOutputCount)
            return console->mode(args->scalarInput[0], args->scalarInput[1]);
        if (selector == 1 && !args->scalarInputCount && !args->scalarOutputCount)
            return console->snapshotArm(this);
        if (selector == 2 && args->scalarInputCount == 3 && args->scalarOutputCount == 1)
            return console->snapshotCommit(this, args->scalarInput[0],
                args->scalarInput[1], args->scalarInput[2], args->scalarOutput);
        if (selector == 3 && !args->scalarInputCount && !args->scalarOutputCount) {
            console->snapshotClose(this); return kIOReturnSuccess;
        }
        return kIOReturnBadArgument;
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
    volatile uint32_t *snapshot = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    if (snapshot[0] == 0x52534731 && snapshot[1] == 32*1024*1024) {
        staging = pci->getDeviceMemoryWithRegister(kIOPCIConfigBaseAddress1);
        if (staging && staging->getLength() == 32*1024*1024) {
            staging->retain(); snapshotAvailable = true;
        } else { staging = nullptr; }
    }
    setProperty("SnapshotProtocol", snapshotAvailable ? 1 : 0, 32);
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
    if (isInactive() || !registers || snapshotOwner) { IOLockUnlock(lock); return kIOReturnNotReady; }
    volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
    vbe[4]=0; OSSynchronizeIO();
    vbe[1]=width; vbe[2]=height; vbe[3]=32; vbe[6]=width; vbe[8]=0; vbe[9]=0;
    OSSynchronizeIO(); vbe[4]=0x41; OSSynchronizeIO();
    const bool matched = vbe[1]==width && vbe[2]==height && vbe[3]==32 && vbe[4]==0x41;
    IOLockUnlock(lock);
    return matched ? kIOReturnSuccess : kIOReturnIOError;
}
// Experimental staging path: ARM once per service instance; user mapping is
// never regranted even after close. Separate BAR1 excludes BAR0 boot writers.
IOReturn RaphaelConsole::snapshotArm(IOUserClient *owner) {
    IOLockLock(lock);
    if (isInactive() || !snapshotAvailable || !registers || snapshotLeased) {
        IOLockUnlock(lock); return kIOReturnNotReady;
    }
    auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    if (r[0] != 0x52534731 || r[2] != 0) {
        IOLockUnlock(lock); return kIOReturnNotReady;
    }
    snapshotLeased = true; // Fail closed even if ARM readback fails.
    r[2] = 1; OSSynchronizeIO();
    bool ok = r[2] == 1 && r[3] == 0;
    if (ok) snapshotOwner = owner;
    else { r[2] = 2; OSSynchronizeIO(); } // Keep lease retired on failed readback.
    IOLockUnlock(lock);
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}
IOReturn RaphaelConsole::snapshotCommit(IOUserClient *owner, uint64_t w,
                                        uint64_t h, uint64_t sequence, uint64_t *ack) {
    if (w < 320 || h < 200 || w > 3840 || h > 2160 ||
        !sequence || sequence > UINT32_MAX || w*h*4 > 32*1024*1024)
        return kIOReturnBadArgument;
    IOLockLock(lock);
    if (isInactive() || !registers || owner != snapshotOwner) {
        IOLockUnlock(lock); return kIOReturnNotReady;
    }
    auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    r[4] = static_cast<uint32_t>(w); r[5] = static_cast<uint32_t>(h);
    // Caller must SFENCE its WC staging writes before entering this method.
    OSSynchronizeIO(); r[6] = static_cast<uint32_t>(sequence); OSSynchronizeIO();
    *ack = r[7];
    bool ok = r[2] == 1 && r[3] == 0 && *ack == sequence;
    IOLockUnlock(lock);
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}
void RaphaelConsole::snapshotClose(IOUserClient *owner) {
    IOLockLock(lock);
    if (owner == snapshotOwner && snapshotOwner) {
        if (registers) {
            auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
            r[2] = 2; OSSynchronizeIO();
        }
        snapshotOwner = nullptr;
    }
    IOLockUnlock(lock);
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
        if (snapshotOwner) {
            auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
            r[2] = 2; OSSynchronizeIO(); snapshotOwner = nullptr;
        }
        volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
        vbe[4]=0; OSSynchronizeIO();
    }
    if (lock) IOLockUnlock(lock);
    IOService::stop(provider);
}
void RaphaelConsole::free() {
    if (registers) { registers->release(); registers=nullptr; }
    if (pixels) { pixels->release(); pixels=nullptr; }
    if (staging) { staging->release(); staging=nullptr; }
    if (lock) { IOLockFree(lock); lock=nullptr; }
    IOService::free();
}
