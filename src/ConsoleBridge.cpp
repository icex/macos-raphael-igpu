// Optional presentation-only bridge to QEMU's Bochs display console.
// Raphael remains the rendering device. No DMA or physical-GPU mappings here.
#ifndef KERNEL
#define KERNEL 1
#endif
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <libkern/OSAtomic.h>
#include <libkern/c++/OSSet.h>
#include <IOKit/pci/IOPCIDevice.h>
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>
#include <kern/clock.h>
#include "ConsoleTiming.hpp"

static uint64_t consoleTimeNS() {
    uint64_t absolute = 0, ns = 0;
    clock_get_uptime(&absolute);
    absolutetime_to_nanoseconds(absolute, &ns);
    return ns;
}

// The slot follows the descriptor, including any retained userspace aliases.
// Client close is not proof that its mapping has disappeared. 128 MiB payload
// maximum; failure refuses ARM rather than sharing or recycling an old bank.
static volatile SInt32 snapshotBuffers = 0;
static constexpr uint32_t snapshotBytes = 32*1024*1024;
class RaphaelConsoleBuffer : public IOBufferMemoryDescriptor {
    OSDeclareDefaultStructors(RaphaelConsoleBuffer)
    bool counted = false;
public:
    static RaphaelConsoleBuffer *allocate() {
        SInt32 count;
        do {
            count = snapshotBuffers;
            if (count >= 4) return nullptr;
        } while (!OSCompareAndSwap(count, count+1, &snapshotBuffers));
        auto *buffer = new RaphaelConsoleBuffer;
        if (!buffer) { OSDecrementAtomic(&snapshotBuffers); return nullptr; }
        buffer->counted = true;
        if (!buffer->initWithPhysicalMask(kernel_task,
                kIODirectionInOut | kIOMemoryKernelUserShared | kIOMapCopybackCache,
                snapshotBytes, PAGE_SIZE, 0)) {
            buffer->release(); return nullptr;
        }
        bzero(buffer->getBytesNoCopy(), snapshotBytes);
        return buffer;
    }
    IOMemoryMap *makeMapping(IOMemoryDescriptor *owner, task_t task,
                            IOVirtualAddress address, IOOptionBits options,
                            IOByteCount offset, IOByteCount length) override {
        const auto cache = options & kIOMapCacheMask;
        if (cache != kIOMapDefaultCache && cache != kIOMapCopybackCache) {
            // On this x86_64 IOKit ABI createMappingInTask passes the newly
            // allocated IOMemoryMap here, including before compatible-map reuse.
            // Reject conflicting aliases; clientMemoryForType options alone are
            // overridden by userspace map flags. Match superclass failure ownership.
            reinterpret_cast<IOMemoryMap *>(address)->release();
            return nullptr;
        }
        return IOBufferMemoryDescriptor::makeMapping(owner, task, address,
                                                      options, offset, length);
    }
    void free() override {
        const bool releaseSlot = counted;
        IOBufferMemoryDescriptor::free();
        // Super frees this and then backing RAM. Never access members afterward.
        if (releaseSlot) OSDecrementAtomic(&snapshotBuffers);
    }
};
class RaphaelConsoleClient;
class RaphaelConsole : public IOService {
    OSDeclareDefaultStructors(RaphaelConsole)
    IOPCIDevice *pci = nullptr;
    IOMemoryMap *registers = nullptr;
    IOMemoryDescriptor *pixels = nullptr;
    IOLock *lock = nullptr;
    OSSet *clients = nullptr;
    IOMemoryDescriptor *staging = nullptr;
    IOUserClient *snapshotOwner = nullptr;
    RaphaelConsoleBuffer *snapshotBuffer = nullptr;
    IOMemoryMap *stagingMap = nullptr;
    bool snapshotRestartable = false;
    bool snapshotPoisoned = false;
    uint32_t snapshotEpoch = 0;
    uint32_t snapshotSequence = 0;
    bool snapshotLeased = false; // Never regrant: mappings may outlive client close.
    bool snapshotAvailable = false;
    bool timingEnabled = false; // Immutable after start; default off.
    ConsoleTiming timing;
    void recordTiming(uint32_t w, uint32_t h, const uint64_t (&t)[8]);
public:
    bool start(IOService *provider) override;
    // Multiple connections may retain retired private mappings, but only one
    // snapshot owner can publish. IOService holds its arbitration lock here.
    bool handleOpen(IOService *client, IOOptionBits, void *) override {
        return !isInactive() && clients &&
            (clients->containsObject(client) ||
             (clients->getCount() < 8 && clients->setObject(client)));
    }
    void handleClose(IOService *client, IOOptionBits) override {
        if (clients) clients->removeObject(client);
    }
    bool handleIsOpen(const IOService *client) const override {
        return clients && (client ? clients->containsObject(client) : clients->getCount() != 0);
    }
    void stop(IOService *provider) override;
    void free() override;
    IOReturn newUserClient(task_t task, void *securityID, UInt32 type,
                          OSDictionary *properties, IOUserClient **handler) override;
    IOReturn mode(uint64_t width, uint64_t height);
    IOReturn memory(IOUserClient *owner, UInt32 type, IOOptionBits *options,
                    IOMemoryDescriptor **memory);
    IOReturn snapshotArm(RaphaelConsoleClient *owner);
    IOReturn snapshotCommit(IOUserClient *owner, uint64_t w, uint64_t h,
                            uint64_t sequence, uint64_t *ack);
    void snapshotClose(IOUserClient *owner, bool finalClose = false);
    void retireLocked();
};
class RaphaelConsoleClient : public IOUserClient {
    OSDeclareDefaultStructors(RaphaelConsoleClient)
    RaphaelConsole *console = nullptr;
    friend class RaphaelConsole;
    bool snapshotAttempted = false;
    RaphaelConsoleBuffer *privateBuffer = nullptr; // Retained through RETIRE for unmap lookup.
public:
    bool start(IOService *provider) override {
        console = OSDynamicCast(RaphaelConsole, provider);
        if (!console || !IOUserClient::start(provider)) return false;
        return console->open(this);
    }
    IOReturn clientClose() override {
        if (console && console->isOpen(this)) { console->snapshotClose(this, true); console->close(this); }
        terminate(); return kIOReturnSuccess;
    }
    void stop(IOService *provider) override {
        if (console && console->isOpen(this)) { console->snapshotClose(this, true); console->close(this); }
        console = nullptr; IOUserClient::stop(provider);
    }
    IOReturn clientMemoryForType(UInt32 type, IOOptionBits *options,
                                 IOMemoryDescriptor **memory) override {
        if (type > 1 || !console || isInactive() || !console->isOpen(this)) return kIOReturnBadArgument;
        return console->memory(this, type, options, memory);
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
OSDefineMetaClassAndStructors(RaphaelConsoleBuffer, IOBufferMemoryDescriptor)
OSDefineMetaClassAndStructors(RaphaelConsole, IOService)
OSDefineMetaClassAndStructors(RaphaelConsoleClient, IOUserClient)

bool RaphaelConsole::start(IOService *provider) {
    uint32_t enabled = 0;
    if (!PE_parse_boot_argn("rgpuconsole", &enabled, sizeof(enabled)) || enabled != 1)
        return false;
    uint32_t diagnostic = 0;
    timingEnabled = PE_parse_boot_argn("rgpuconsoletiming", &diagnostic, sizeof(diagnostic)) && diagnostic == 1;
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
    clients = OSSet::withCapacity(8);
    if (!registers || registers->getLength() != 4096 || !lock || !clients) return false;
    volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
    if (vbe[0] != 0xb0c5) return false;
    volatile uint32_t *snapshot = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    if ((snapshot[0] == 0x52534731 || snapshot[0] == 0x52534732) &&
            snapshot[1] == snapshotBytes) {
        staging = pci->getDeviceMemoryWithRegister(kIOPCIConfigBaseAddress1);
        if (staging && staging->getLength() == 32*1024*1024) {
            staging->retain();
            stagingMap = staging->map(kIOMapWriteCombineCache);
            snapshotAvailable = stagingMap && stagingMap->getLength() == snapshotBytes;
            snapshotRestartable = snapshotAvailable && snapshot[0] == 0x52534732;
        } else { staging = nullptr; }
    }
    setProperty("SnapshotProtocol", snapshotAvailable ? 1 : 0, 32);
    setProperty("SnapshotRestartable", snapshotRestartable ? 1 : 0, 32);
    setProperty("SnapshotPrivateBufferLimit", 4, 32);
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
// Retain under the same lock used by close, including while type1 is mapped.
IOReturn RaphaelConsole::memory(IOUserClient *owner, UInt32 type,
                                IOOptionBits *options, IOMemoryDescriptor **memory) {
    IOLockLock(lock);
    *memory = nullptr;
    if (!isInactive()) {
        if (!type) *memory = pixels;
        else *memory = static_cast<RaphaelConsoleClient *>(owner)->privateBuffer;
        // Apple's unmap path asks clientMemoryForType again. Retired owners
        // must still resolve their own descriptor, never the active owner's.
    }
    if (*memory) (*memory)->retain();
    *options = 0;
    IOLockUnlock(lock);
    return *memory ? kIOReturnSuccess : kIOReturnNotReady;
}
// Called under lock. Detach before releasing the descriptor. Stale userspace
// aliases retain private RAM and cannot write kernel-only BAR1 or a new owner.
void RaphaelConsole::retireLocked() {
    if (snapshotOwner && registers) {
        auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
        if (snapshotRestartable) { r[12] = snapshotEpoch; OSSynchronizeIO(); }
        r[2] = 2; OSSynchronizeIO();
        if (r[2] != 2 || (snapshotRestartable && r[13] != snapshotEpoch))
            snapshotPoisoned = true;
    }
    snapshotOwner = nullptr;
    if (snapshotBuffer) { snapshotBuffer->release(); snapshotBuffer = nullptr; }
}
IOReturn RaphaelConsole::snapshotArm(RaphaelConsoleClient *owner) {
    // Allocation may block; no provider lock or interrupt context is held here.
    auto *fresh = RaphaelConsoleBuffer::allocate();
    if (!fresh) return kIOReturnNoMemory;
    IOLockLock(lock);
    if (isInactive() || !snapshotAvailable || !registers || snapshotOwner ||
            snapshotPoisoned || owner->snapshotAttempted ||
            (!snapshotRestartable && snapshotLeased)) {
        IOLockUnlock(lock); fresh->release(); return kIOReturnNotReady;
    }
    auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    const uint32_t magic = snapshotRestartable ? 0x52534732 : 0x52534731;
    const uint32_t state = r[2];
    if (r[0] != magic || (state != 0 && !(snapshotRestartable && state == 2)) ||
            (snapshotRestartable && (snapshotEpoch == UINT32_MAX || r[13] != snapshotEpoch))) {
        snapshotPoisoned = true;
        IOLockUnlock(lock); fresh->release(); return kIOReturnNotReady;
    }
    owner->snapshotAttempted = true; // No re-ARM on this connection, even on ambiguity.
    snapshotLeased = true;
    if (snapshotRestartable) { ++snapshotEpoch; r[12] = snapshotEpoch; OSSynchronizeIO(); }
    r[2] = 1; OSSynchronizeIO();
    bool ok = r[2] == 1 && r[3] == 0 && r[7] == 0 &&
        (!snapshotRestartable || r[13] == snapshotEpoch);
    if (ok) {
        snapshotOwner = owner; snapshotBuffer = fresh; snapshotSequence = 0;
        fresh->retain(); owner->privateBuffer = fresh;
    } else {
        snapshotPoisoned = true; // Never infer a safe new epoch after ambiguous ARM.
        r[2] = 2; OSSynchronizeIO(); fresh->release();
    }
    IOLockUnlock(lock);
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}
IOReturn RaphaelConsole::snapshotCommit(IOUserClient *owner, uint64_t w,
                                        uint64_t h, uint64_t sequence, uint64_t *ack) {
    *ack = 0;
    if (w < 320 || h < 200 || w > 3840 || h > 2160 ||
        !sequence || sequence > UINT32_MAX || w*h*4 > snapshotBytes)
        return kIOReturnBadArgument;
    uint64_t t[8] = {};
    if (timingEnabled) t[0] = consoleTimeNS();
    IOLockLock(lock);
    if (timingEnabled) t[1] = consoleTimeNS();
    if (isInactive() || !registers || owner != snapshotOwner || !snapshotBuffer ||
            !stagingMap || snapshotPoisoned) {
        IOLockUnlock(lock); return kIOReturnNotReady;
    }
    if (snapshotSequence == UINT32_MAX || sequence != uint64_t(snapshotSequence)+1) {
        IOLockUnlock(lock); return kIOReturnBadArgument;
    }
    auto *r = reinterpret_cast<volatile uint32_t *>(registers->getVirtualAddress()+0x700);
    if (timingEnabled) t[2] = consoleTimeNS();
    if (r[2] != 1 || r[3] != 0 || r[7] != snapshotSequence ||
            (snapshotRestartable && r[13] != snapshotEpoch)) {
        snapshotPoisoned = true; retireLocked();
        IOLockUnlock(lock); return kIOReturnIOError;
    }
    if (timingEnabled) t[3] = consoleTimeNS();
    // Cooperating caller fences and stops touching this private buffer until ACK.
    // Kernel serialization prevents close/new-owner handoff during the copy.
    memcpy(reinterpret_cast<void *>(stagingMap->getVirtualAddress()),
           snapshotBuffer->getBytesNoCopy(), static_cast<size_t>(w*h*4));
    __asm__ volatile("sfence" ::: "memory");
    if (timingEnabled) t[4] = consoleTimeNS();
    if (snapshotRestartable) { r[12] = snapshotEpoch; OSSynchronizeIO(); }
    r[4] = static_cast<uint32_t>(w); r[5] = static_cast<uint32_t>(h);
    OSSynchronizeIO();
    if (timingEnabled) t[5] = consoleTimeNS();
    r[6] = static_cast<uint32_t>(sequence); OSSynchronizeIO();
    if (timingEnabled) t[6] = consoleTimeNS();
    bool ok = r[2] == 1 && r[3] == 0 && r[7] == sequence &&
        (!snapshotRestartable || r[13] == snapshotEpoch);
    if (timingEnabled) t[7] = consoleTimeNS();
    if (ok) { snapshotSequence = sequence; *ack = sequence; }
    else { snapshotPoisoned = true; retireLocked(); }
    if (ok && timingEnabled) recordTiming(w, h, t);
    IOLockUnlock(lock);
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}
// Called under provider lock. Reporting cost is deliberately outside measured stages.
void RaphaelConsole::recordTiming(uint32_t w, uint32_t h, const uint64_t (&t)[8]) {
    for (unsigned i = 1; i < 8; ++i) if (t[i] < t[i-1]) return;
    const uint64_t ns[5] = {t[1]-t[0], t[4]-t[3], t[5]-t[4], t[6]-t[5],
                           (t[3]-t[2]) + (t[7]-t[6])};
    if (!timing.record(t[7], w, h, ns)) return;
    for (const auto &b : timing.buckets) if (b.count) {
        IOLog(CONSOLE_TIMING_LINE1,
              timing.reports+1, t[7]-timing.started, b.width, b.height, b.count,
              timing.saturated, b.total[0], b.maximum[0], b.total[1], b.maximum[1],
              b.total[2], b.maximum[2]);
        IOLog(CONSOLE_TIMING_LINE2,
              timing.reports+1, t[7]-timing.started, b.width, b.height, b.count,
              timing.saturated, b.total[3], b.maximum[3], b.total[4], b.maximum[4],
              timing.dropped);
    }
    timing.clearWindow(t[7]);
}
void RaphaelConsole::snapshotClose(IOUserClient *owner, bool finalClose) {
    IOLockLock(lock);
    // Also excludes a concurrent ARM still allocating before client close.
    static_cast<RaphaelConsoleClient *>(owner)->snapshotAttempted = true;
    if (owner == snapshotOwner && snapshotOwner) retireLocked();
    auto *client = static_cast<RaphaelConsoleClient *>(owner);
    if (finalClose && client->privateBuffer) {
        auto *retired = client->privateBuffer;
        client->privateBuffer = nullptr;
        retired->release();
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
        retireLocked();
        volatile uint16_t *vbe = reinterpret_cast<volatile uint16_t *>(registers->getVirtualAddress()+0x500);
        vbe[4]=0; OSSynchronizeIO();
    }
    if (lock) IOLockUnlock(lock);
    IOService::stop(provider);
}
void RaphaelConsole::free() {
    if (registers) { registers->release(); registers=nullptr; }
    if (pixels) { pixels->release(); pixels=nullptr; }
    if (snapshotBuffer) { snapshotBuffer->release(); snapshotBuffer=nullptr; }
    if (stagingMap) { stagingMap->release(); stagingMap=nullptr; }
    if (staging) { staging->release(); staging=nullptr; }
    if (clients) { clients->release(); clients=nullptr; }
    if (lock) { IOLockFree(lock); lock=nullptr; }
    IOService::free();
}
