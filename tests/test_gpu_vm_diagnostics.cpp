#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../src/GpuVmDiagnostics.hpp"
#include "../src/ObservationBuffer.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    alignas(uint64_t) unsigned char bytes[0x28] {};
    auto put32 = [&](size_t offset, uint32_t value) {
        std::memcpy(bytes + offset, &value, sizeof(value));
    };
    auto put64 = [&](size_t offset, uint64_t value) {
        std::memcpy(bytes + offset, &value, sizeof(value));
    };
    put32(0, 0);
    put32(4, 2);
    put64(8, 0x400000000ULL);
    put64(0x10, 0x400ffffffULL);
    put64(0x18, 0x840abc000ULL);
    put32(0x20, 3);
    bytes[0x24] = 1;

    auto request = RaphaelVm::observeInvalidateRequest(bytes, sizeof(bytes));
    require(request.valid && request.hub == 0 && request.vmid == 2,
            "the selected GFXHUB VMID is captured");
    require(request.start == 0x400000000ULL && request.end == 0x400ffffffULL &&
                request.root == 0x840abc000ULL && request.flags == 3 &&
                request.reprogram,
            "the complete native invalidate request is captured");
    require(!RaphaelVm::observeInvalidateRequest(bytes, 0x27).valid,
            "a truncated invalidate request is rejected");

    alignas(uint32_t) unsigned char prepared[0x54] {};
    for (size_t i = 0; i < 0x54 / sizeof(uint32_t); ++i) {
        const uint32_t value = 0x1000u + static_cast<uint32_t>(i);
        std::memcpy(prepared + i * sizeof(uint32_t), &value, sizeof(value));
    }
    auto program = RaphaelVm::observePreparedRequest(
        bytes, sizeof(bytes), prepared, sizeof(prepared), true);
    require(program.valid && program.request.valid && program.request.vmid == 2 &&
                program.alternate,
            "the prepared request remains tied to its source VMID and packet variant");
    require(program.words[0] == 0x1000 && program.words[10] == 0x100a &&
                program.words[20] == 0x1014,
            "all 21 prepared register/value dwords are copied after native encoding");
    require(program.infoWords[0] == 0 && program.infoWords[1] == 2 &&
                program.infoWords[9] == 1,
            "all 10 source request dwords are retained without normalization");
    bytes[0x25] = 0xa5;
    bytes[0x26] = 0x5a;
    bytes[0x27] = 0xc3;
    program = RaphaelVm::observePreparedRequest(
        bytes, sizeof(bytes), prepared, sizeof(prepared), false);
    require(program.infoWords[9] == 0xc35aa501,
            "reserved source bytes survive the bounded copy");
    require(!RaphaelVm::observePreparedRequest(
                bytes, sizeof(bytes), prepared, 0x50, true).valid,
            "a truncated prepared request is rejected");

    constexpr auto vmid0 = RaphaelVm::contextRegisters(0);
    constexpr auto vmid2 = RaphaelVm::contextRegisters(2);
    constexpr auto invalid = RaphaelVm::contextRegisters(16);
    require(vmid0.valid && vmid0.control == 0x15fc && vmid0.ptbLo == 0x1667 &&
                vmid0.startLo == 0x1687 && vmid0.endLo == 0x16a7,
            "VMID 0 uses the GC 10.3 context-zero register set");
    require(vmid2.valid && vmid2.control == 0x15fe && vmid2.ptbLo == 0x166b &&
                vmid2.ptbHi == 0x166c && vmid2.startLo == 0x168b &&
                vmid2.startHi == 0x168c && vmid2.endLo == 0x16ab &&
                vmid2.endHi == 0x16ac,
            "VMID 2 applies the documented one/two-register strides");
    require(!invalid.valid, "VMIDs outside the 16 hardware contexts are rejected");

    rgpu::ObservationBuffer<RaphaelVm::InvalidateRequest, 2> observations;
    observations.append(request);
    observations.append(request);
    observations.append(request);
    RaphaelVm::InvalidateRequest copied {};
    require(observations.size() == 2 && observations.dropped() == 1,
            "the lock-free observation buffer is bounded");
    require(observations.read(0, copied) && copied.vmid == 2 &&
                copied.root == request.root,
            "a published observation is copied intact");
    require(!observations.read(2, copied),
            "an overflowed observation is never exposed as a slot");

    std::puts("GPU VM diagnostic fixtures passed");
}
