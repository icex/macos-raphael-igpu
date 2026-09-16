#ifndef RAPHAEL_VCN_PLATFORM_POWER_HPP
#define RAPHAEL_VCN_PLATFORM_POWER_HPP
#include <stdint.h>
namespace RaphaelVcnPower {
// Raphael MP1 13.0.5 only. Source: smu_v13_0_5_ppt.c/ppsmc.h.
constexpr uint32_t Message = 0x03b10508, Response = 0x03b10984, Argument = 0x03b10988;
constexpr uint32_t ExpectedVersion = 0x00625300; // current host GetSmuVersion receipt89
// smu_v13_0_5_ppsmc.h message ids used here. Never Navi PPSMC ids.
constexpr uint32_t MsgGetSmuVersion = 2, MsgPowerDownVcn = 5, MsgPowerUpVcn = 6,
    MsgSetHardMinVcn = 7, MsgGetGfxclkFrequency = 15, MsgGetEnabledSmuFeatures = 16,
    MsgSetSoftMaxVcn = 17;
struct Result {
    uint32_t error = 0, pre = 0, version = 0, response = 0, downResponse = 0;
    // Optional, non-fatal telemetry/clock request results (0 = not attempted).
    uint32_t gfxclkResponse = 0, gfxclkMHz = 0, featuresResponse = 0, featuresLow = 0,
        featuresHigh = 0, clockMinResponse = 0, clockMaxResponse = 0;
};
// After a successful PowerUpVcn, `query` reads GetGfxclkFrequency and the enabled
// feature mask, and `vcnClockMHz` (nonzero) requests SetHardMinVcn/SetSoftMaxVcn at
// that frequency exactly as Linux smu_v13_0_5_set_soft_freq_limited_range does for
// SMU_VCLK. Neither changes `error`: VCN initialization proceeds regardless, and the
// firmware's own response codes are recorded for the serial log.
template<class Read, class Write, class Delay>
Result enable(Read read, Write write, Delay delay, bool cycle = false,
              uint32_t vcnClockMHz = 0, bool query = false) {
    Result result;
    auto poll = [&]() {
        uint32_t response = read(Response);
        for (unsigned n = 0; response == 0 && n < 1000; ++n) {
            delay(); response = read(Response);
        }
        return response;
    };
    result.pre = poll();
    if (result.pre != 1) { result.error = 1; return result; }
    auto sendWith = [&](uint32_t command, uint32_t parameter) {
        write(Response, 0); write(Argument, parameter); write(Message, command);
        return poll();
    };
    auto send = [&](uint32_t command) { return sendWith(command, 0); };
    result.response = send(MsgGetSmuVersion); // no power mutation yet
    if (result.response != 1) { result.error = 2; return result; }
    result.version = read(Argument);
    if (result.version != ExpectedVersion) { result.error = 3; return result; }
    if (cycle) {
        result.downResponse = send(MsgPowerDownVcn); // Raphael PowerDownVcn, parameter0
        if (result.downResponse != 1) { result.error = 5; return result; }
    }
    result.response = send(MsgPowerUpVcn); // PowerUpVcn, parameter0, never Navi's message enum
    if (result.response != 1) { result.error = 4; return result; }
    if (query) {
        result.gfxclkResponse = send(MsgGetGfxclkFrequency);
        if (result.gfxclkResponse == 1) result.gfxclkMHz = read(Argument);
        result.featuresResponse = sendWith(MsgGetEnabledSmuFeatures, 0);
        if (result.featuresResponse == 1) {
            result.featuresLow = read(Argument);
            if (sendWith(MsgGetEnabledSmuFeatures, 1) == 1) result.featuresHigh = read(Argument);
        }
    }
    if (vcnClockMHz) {
        result.clockMinResponse = sendWith(MsgSetHardMinVcn, vcnClockMHz);
        if (result.clockMinResponse == 1)
            result.clockMaxResponse = sendWith(MsgSetSoftMaxVcn, vcnClockMHz);
    }
    return result;
}
}
#endif
