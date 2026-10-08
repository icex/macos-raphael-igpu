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
