#ifndef RAPHAEL_VCN_PLATFORM_POWER_HPP
#define RAPHAEL_VCN_PLATFORM_POWER_HPP
#include <stdint.h>
namespace RaphaelVcnPower {
// Raphael MP1 13.0.5 only. Source: smu_v13_0_5_ppt.c/ppsmc.h.
constexpr uint32_t Message = 0x03b10508, Response = 0x03b10984, Argument = 0x03b10988;
constexpr uint32_t ExpectedVersion = 0x00625300; // current host GetSmuVersion receipt89
struct Result { uint32_t error = 0, pre = 0, version = 0, response = 0; };
template<class Read, class Write, class Delay>
Result enable(Read read, Write write, Delay delay) {
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
    auto send = [&](uint32_t command) {
        write(Response, 0); write(Argument, 0); write(Message, command);
        return poll();
    };
    result.response = send(2); // GetSmuVersion; no power mutation yet
    if (result.response != 1) { result.error = 2; return result; }
    result.version = read(Argument);
    if (result.version != ExpectedVersion) { result.error = 3; return result; }
    result.response = send(6); // PowerUpVcn, parameter0, never Navi's message enum
    if (result.response != 1) result.error = 4;
    return result;
}
}
#endif
