#include <cstdio>
#include <cstdlib>
#include "../src/GfxHangDump.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

int main() {
    using namespace RaphaelHang;

    // Candidate 211: RB0_BASE=0_ffbfe000 CNTL=0xa00e10 RPTR=0x1e31 WPTR=0x2000.
    const auto ring = ringGeometry(0xffbfe000u, 0, 0xa00e10u);
    require(ring.valid, "candidate 211 ring registers decode");
    require(ring.va == 0xffbfe00000ULL, "ring base is the register shifted by eight bits");
    require(ring.dwords == 0x20000u, "RB_BUFSZ 16 is a 0x80000-byte ring");
    require(!ringGeometry(0, 0, 0xa00e10u).valid, "a zero base is refused");
    require(!ringGeometry(0xffbfe000u, 0, 0xa00e00u).valid, "a zero RB_BUFSZ is refused");
    require(!ringGeometry(0, 0x10000u, 0x10u).valid, "a base beyond 48 bits is refused");

    require(ringIndex(0x1e31u, -64, ring.dwords) == 0x1df1u, "64 dwords before RPTR");
    require(ringIndex(0x10u, -64, ring.dwords) == 0x1ffd0u, "window before RPTR wraps");
    require(ringIndex(0x1fff0u, 32, ring.dwords) == 0x10u, "window after RPTR wraps");
    require(ringIndex(5, 1, 3) == 0, "non power-of-two ring sizes are refused");

    require(ringStalled(0x1e31u, 0x2000u, 0x1e31u), "static RPTR with pending data stalls");
    require(!ringStalled(0x2000u, 0x2000u, 0x2000u), "an empty ring is idle");
    require(!ringStalled(0x1e31u, 0x2000u, 0x1e41u), "a moving RPTR is progress");

    const uint32_t words[] {0x80000000u, 0xc0023f00u, 0x00401003u, 0x00000004u,
                            0x03800120u, 0xc0023300u, 0x10000000u, 0, 0x02000010u};
    const auto ib = parseIndirectBuffer(words, 9, 1);
    require(ib.valid && ib.opcode == kPacket3IndirectBuffer, "INDIRECT_BUFFER header");
    require(ib.address == 0x400401000ULL, "IB address drops the swap bits");
    require(ib.lengthDwords == 0x120u && ib.vmid == 3u, "control carries length and VMID");
    const auto ce = parseIndirectBuffer(words, 9, 5);
    require(ce.valid && ce.opcode == kPacket3IndirectBufferConst && ce.vmid == 2u,
            "INDIRECT_BUFFER_CONST header");
    require(!parseIndirectBuffer(words, 9, 0).valid, "PACKET2 filler is not an IB");
    require(!parseIndirectBuffer(words, 8, 5).valid, "a truncated IB packet is refused");
    const uint32_t zeroLength[] {0xc0023f00u, 0x1000u, 0, 0x03000000u};
    require(!parseIndirectBuffer(zeroLength, 4, 0).valid, "a zero-length IB is refused");

    require(packetCoversBase(ib, 0x00401000u, 4u), "IB1 base at the buffer start");
    require(packetCoversBase(ib, 0x00401480u, 4u), "IB1 base at the fetch position");
    require(!packetCoversBase(ib, 0x00401484u, 4u), "IB1 base past the buffer end");
    require(!packetCoversBase(ib, 0x00401000u, 5u), "IB1 base in another address space");

    const auto clipped = windowAround(0x10u, 48, 16, 0x120u);
    require(clipped.valid && clipped.first == 0 && clipped.count == 0x20u,
            "window clips at the buffer start");
    const auto tail = windowAround(0x118u, 48, 16, 0x120u);
    require(tail.valid && tail.first == 0xe8u && tail.count == 0x38u,
            "window clips at the buffer end");
    require(!windowAround(0x121u, 48, 16, 0x120u).valid, "a cursor past the end is refused");
    const auto open = windowAround(0x200u, 48, 16, 0);
    require(open.valid && open.first == 0x1d0u && open.count == 64u,
            "unknown length keeps the full window");

    const auto both = ibCursor(0x40u, 0xe0u, 0x120u);
    require(both.offsetValid && both.offset == 0x40u && both.remainingValid &&
            both.remaining == 0x40u, "both cursor readings agree");
    const auto bytes = ibCursor(0x480u, 0x200u, 0x120u);
    require(!bytes.offsetValid && !bytes.remainingValid, "out-of-range readings are refused");
    const auto unknown = ibCursor(0x40u, 0x10u, 0);
    require(unknown.offsetValid && !unknown.remainingValid, "unknown length keeps OFFSET only");

    // depth 3 (control bits 2:1), block size 0: leaf width 9.
    const uint32_t control = 1u | (3u << 1);
    require(entryShift(control, 0) == 12u, "leaf entries map 4 KiB pages");
    require(entryShift(control, 1) == 21u, "level-1 entries span 2 MiB");
    require(entryShift(control, 2) == 30u, "level-2 entries span 1 GiB");
    uint64_t page = 0;
    require(leafPage(0x84b6f3000ULL, control, 0, 0x401234ULL, page) && page == 0x84b6f3000ULL,
            "a 4 KiB leaf is its own page");
    require(leafPage(0x84b600000ULL, control, 1, 0x4c1234ULL, page) && page == 0x84b6c1000ULL,
            "a 2 MiB PDE-as-PTE adds the page offset inside the span");
    require(entryShift(0, 0) == 12u && entryShift(0, 1) == 48u, "flat tables have one level");
    require(!leafPage(0x1000ULL, 0, 1, 0, page), "an impossible span is refused");

    uint64_t offset = 0;
    require(framebufferOffset(0x840123000ULL, 0xf400000000ULL, 0x840000000ULL,
                              0x10000000ULL, offset) && offset == 0x123000ULL,
            "physical framebuffer address");
    require(framebufferOffset(0xf400456000ULL, 0xf400000000ULL, 0x840000000ULL,
                              0x10000000ULL, offset) && offset == 0x456000ULL,
            "logical MC address");
    require(!framebufferOffset(0x850000000ULL, 0xf400000000ULL, 0x840000000ULL,
                               0x10000000ULL, offset), "beyond the visible BAR is refused");
    require(!framebufferOffset(0x840123004ULL, 0xf400000000ULL, 0x840000000ULL,
                               0x10000000ULL, offset), "an unaligned page is refused");
    std::puts("gfx hang dump arithmetic: ok");
    return 0;
}
