#pragma once
#include <stdint.h>
namespace RaphaelDisplayPower {
// Linux dcn315_smu.c: VBIOS mailbox C2PMSG3/37/38, not the driver mailbox.
constexpr uint32_t Message=0x03b1050c, Argument=0x03b10994, Response=0x03b10998;
struct Result { uint32_t pre=0, versionResponse=0, version=0, wakeResponse=0, dcfResponse=0, dcfMHz=0; };
template<class Read, class Write, class Delay>
Result exitIdle(Read read, Write write, Delay delay, uint32_t expectedVersion, uint32_t dcfMHz=0) {
    Result r;
    auto poll = [&]() {
        uint32_t value=read(Response);
        for (unsigned n=0; value==0 && n<500; n++) { delay(); value=read(Response); }
        return value;
    };
    r.pre=poll();
    if (r.pre!=1) return r;
    auto send = [&](uint32_t command, uint32_t argument=0) {
        write(Response,0); write(Argument,argument); write(Message,command);
        return poll();
    };
    r.versionResponse=send(2); // GetPmfwVersion
    if (r.versionResponse!=1) return r;
    r.version=read(Argument);
    if (r.version!=expectedVersion) return r;
    r.wakeResponse=send(0x12); // SetDisplayIdleOptimizations(0): mission mode
    // Linux dcn315_update_clocks restores hard-min DCFCLK after mission mode.
    // Bound the diagnostic to the known host request; never invent an OC value.
    if (r.wakeResponse==1 && dcfMHz==1000) {
        r.dcfResponse=send(7,dcfMHz);
        if (r.dcfResponse==1) r.dcfMHz=read(Argument);
    }
    return r;
}
}
