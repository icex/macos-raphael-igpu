#pragma once
#include <stdint.h>

namespace RaphaelConsoleTmr {
// Live DMCUB state required immediately before PSP may replace its TMR.
// A completed MODE2 or an old recovery receipt is not a substitute for this.
inline bool held(uint32_t control, uint32_t reset, uint32_t interfaceControl) {
    return control != UINT32_MAX && reset != UINT32_MAX &&
           interfaceControl != UINT32_MAX && !(control & 0x10000u) &&
           (reset & 1u) && (interfaceControl & 0x100u);
}
// An opt-in console-only cold path. A missing version alone is not enough:
// both executable windows must be entirely empty and the CPU already in reset.
template<class IO> bool emptyFirmware(IO &io) {
    if (io.read(0x36a3) != 0 || io.read(0x36a4) != 0 ||
        io.read(0x36c0) != 1) return false;
    for (unsigned cw=0; cw<2; ++cw) {
        if (io.read(0x3665+cw) || io.read(0x366d+cw) ||
            io.read(0x3675+2*cw) || io.read(0x3676+2*cw)) return false;
    }
    for (unsigned region=0; region<3; ++region)
        if (io.read(0x364e + 2*region) || io.read(0x364f+2*region) ||
            io.read(0x365e + region)) return false;
    return true;
}
template<class IO> bool holdEmptyFirmware(IO &io) {
    if (!emptyFirmware(io)) return false;
    const auto control=io.read(0x36b6), interfaceControl=io.read(0x3802);
    // Observed disabled/default-enable states only; never stop a running CPU.
    if ((control != 0 && control != 0x80000 && control != 0x90000) ||
        (interfaceControl != 0 && interfaceControl != 0x100)) return false;
    // Complete the DCN31 reset order while processor reset is already asserted.
    if (!emptyFirmware(io)) return false;
    io.write(0x3802, interfaceControl | 0x100);
    if (io.read(0x3802) != (interfaceControl | 0x100) || !emptyFirmware(io)) return false;
    io.write(0x36b6, control & ~0x10000u);
    return emptyFirmware(io) && held(io.read(0x36b6),io.read(0x36c0),io.read(0x3802));
}
// Linux dmub_dcn31_reset also clears ENABLE when CPU reset is already set.
// Here both resets must already be asserted; never stop/start a running image.
template<class IO> bool disableWhileReset(IO &io) {
    const auto control=io.read(0x36b6), reset=io.read(0x36c0), interfaceControl=io.read(0x3802);
    if (control==UINT32_MAX || reset==UINT32_MAX || interfaceControl==UINT32_MAX ||
        !(reset&1u) || !(interfaceControl&0x100u)) return false;
    if (control&0x10000u) io.write(0x36b6,control&~0x10000u);
    return held(io.read(0x36b6),io.read(0x36c0),io.read(0x3802));
}
template<class IO, class Replace> uint32_t replace(bool reserved, IO &io, Replace operation) {
    if (!reserved) return 2;
    const auto control=io.read(0x36b6), reset=io.read(0x36c0), interfaceControl=io.read(0x3802);
    if (!held(control,reset,interfaceControl)) return 2;
    return operation();
}
}
