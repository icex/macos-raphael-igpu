#pragma once
#include <stdint.h>
#include <stddef.h>

namespace RaphaelHostMemory {
struct Window { uint64_t address, bytes; };
struct Plan { uint64_t limit, reserved, additional; };
// Firmware code uses CPU-physical offsets; mailbox windows use MC addresses.
// Preserve the entire 32MiB-aligned tail containing every live host window.
inline bool plan(uint64_t mcBase, uint64_t physicalBase, uint64_t total,
                 uint64_t visible, uint64_t existing, const Window *windows,
                 size_t count, Plan &out) {
    if (!mcBase || !physicalBase || !total || !visible || visible > total ||
        existing > total || !windows || count < 2) return false;
    uint64_t lowest = total;
    for (size_t i = 0; i < count; ++i) {
        uint64_t off;
        const auto &w = windows[i];
        if (!w.bytes) return false;
        if (w.address >= mcBase && w.address - mcBase < total)
            off = w.address - mcBase;
        else if (w.address >= physicalBase && w.address - physicalBase < total)
            off = w.address - physicalBase;
        else return false;
        if (w.bytes > total - off) return false;
        if (off < lowest) lowest = off;
    }
    const uint64_t cap = lowest & ~uint64_t(0x1ffffff);
    if (cap < visible || cap >= total) return false;
    const uint64_t reserve = total - cap;
    const uint64_t chosen = existing > reserve ? existing : reserve;
    if (chosen > total - visible) return false;
    out = {total - chosen, chosen, chosen - existing};
    return true;
}
}
