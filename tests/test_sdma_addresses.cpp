#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "../src/SdmaAddresses.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    // Exact 24G830 disassembly: flags at +0, VMID at +4, entry count at
    // +0x14, then one qword GPU virtual address at +0x58 + 0x28*i.
    alignas(uint64_t) unsigned char submit[0xe8] {};
    auto put32 = [&](size_t offset, uint32_t value) {
        std::memcpy(submit + offset, &value, sizeof(value));
    };
    auto put64 = [&](size_t offset, uint64_t value) {
        std::memcpy(submit + offset, &value, sizeof(value));
    };
    put32(0, 0x12345678);
    put32(4, 2);
    put32(0x14, 3);
    put64(0x58, 0x400100020ULL);
    put64(0x80, 0xffbff40000ULL);
    put64(0xa8, 0x401180000ULL);

    unsigned char before[sizeof(submit)];
    std::memcpy(before, submit, sizeof(submit));
    auto observation = RaphaelSdma::observeSubmitInfo(submit, sizeof(submit));
    require(observation.layoutValid && observation.entries == 3,
            "the measured three-entry submit layout is accepted");
    require(observation.flags == 0x12345678 && observation.vmid == 2,
            "the SDMA packet flags and VMID are captured");
    require(observation.addresses[0] == 0x400100020ULL &&
                observation.addresses[1] == 0xffbff40000ULL &&
                observation.addresses[2] == 0x401180000ULL,
            "every measured GPU virtual address is captured");
    require(std::memcmp(before, submit, sizeof(submit)) == 0,
            "observing a VMID-relative submit never rewrites its addresses");

    put32(0x14, 5);
    auto tooMany = RaphaelSdma::observeSubmitInfo(submit, sizeof(submit));
    require(!tooMany.layoutValid && tooMany.entries == 5,
            "an entry count beyond the measured structure fails closed");
    auto tooShort = RaphaelSdma::observeSubmitInfo(submit, 0x5f);
    require(!tooShort.layoutValid,
            "a truncated submit structure cannot expose a partial address");
    auto missing = RaphaelSdma::observeSubmitInfo(nullptr, sizeof(submit));
    require(!missing.layoutValid,
            "a missing submit structure is rejected");

    std::puts("SDMA submit observation fixtures passed");
}
