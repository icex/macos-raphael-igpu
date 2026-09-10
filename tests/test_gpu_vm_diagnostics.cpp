#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
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

    unsigned char callerBefore[sizeof(bytes)];
    std::memcpy(callerBefore, bytes, sizeof(bytes));
    put64(0x18, 0xf401234001ULL);
    auto local = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
    require((reinterpret_cast<uintptr_t>(local.bytes) & (alignof(uint64_t) - 1)) == 0,
            "the private native invalidate request satisfies its uint64 ABI alignment");
    require(local.valid && local.eligible && local.repaired &&
                local.originalRoot == 0xf401234001ULL &&
                local.nativeRoot == 0x841234001ULL,
            "Raphael VMID2 logical root is converted from MC to physical FB space");
    require(RaphaelVm::readU64(local.bytes + 0x18) == 0x841234001ULL,
            "only the local invalidate copy carries the physical root");
    require(std::memcmp(callerBefore, bytes, 0x18) == 0 &&
                std::memcmp(callerBefore + 0x20, bytes + 0x20, 8) == 0 &&
                RaphaelVm::readU64(bytes + 0x18) == 0xf401234001ULL,
            "the caller-owned invalidate request remains untouched");

    // Candidate 179 captured this exact VMID2 request immediately before the
    // first real SDMA PAGE submission. Apple's native encoder accepts the
    // zero-attribute root and copies it into the PTB register words unchanged.
    put64(8, 0);
    put64(0x10, UINT64_MAX);
    put64(0x18, 0xf40b6f3000ULL);
    put32(0x20, 0xff);
    auto captured179 = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
    require(captured179.valid && captured179.eligible && captured179.repaired &&
                captured179.originalRoot == 0xf40b6f3000ULL &&
                captured179.nativeRoot == 0x84b6f3000ULL &&
                RaphaelVm::readU64(captured179.bytes + 0x18) == 0x84b6f3000ULL,
            "candidate 179 zero-attribute VMID2 root is converted without adding flags");

    put64(8, 0x400000000ULL);
    put64(0x10, 0x400ffffffULL);

    put64(0x18, 0xf401234005ULL);
    auto cached = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
    require(cached.repaired && cached.nativeRoot == 0x841234005ULL,
            "the observed CACHE bit is retained across root conversion");
    put64(0x18, 0xf401234041ULL);
    auto sixtyFourByte = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
    require(sixtyFourByte.repaired && sixtyFourByte.nativeRoot == 0x841234041ULL,
            "PDE address bits 11:6 survive the 64-byte-aligned conversion");
    for (uint64_t rejected : {0xf401234003ULL, 0xf401234009ULL,
                              0x8401234001ULL, 0x841234001ULL}) {
        put64(0x18, rejected);
        auto result = RaphaelVm::prepareInvalidateInfo(
            bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
        require(result.valid && !result.repaired,
                "SYSTEM, unknown, outside-MC, and already-physical roots fail closed");
    }
    put64(0x18, 0xf401234001ULL);
    for (unsigned variant = 0; variant < 5; ++variant) {
        put32(0, variant == 0 ? 1 : 0);
        put32(4, variant == 1 ? 0 : (variant == 2 ? 16 : 2));
        bytes[0x24] = variant == 3 ? 0 : 1;
        auto result = RaphaelVm::prepareInvalidateInfo(
            bytes, sizeof(bytes), variant == 4 ? false : true, true,
            0xf400, 0xf41f, 0x840);
        require(!result.repaired,
                "only enabled hub0 VMID2 reprogram requests are eligible");
    }
    put32(0, 0); put32(4, 2); bytes[0x24] = 1;
    require(!RaphaelVm::prepareInvalidateInfo(
                bytes, 0x27, true, true, 0xf400, 0xf41f, 0x840).valid,
            "a truncated invalidate request cannot be copied or repaired");
    require(RaphaelVm::prepareInvalidateInfo(
                bytes, 0x27, true, true, 0xf400, 0xf41f, 0x840).reason ==
                RaphaelVm::RootRepairReason::InvalidInput &&
            RaphaelVm::prepareInvalidateInfo(
                bytes, sizeof(bytes), false, true, 0xf400, 0xf41f, 0x840).reason ==
                RaphaelVm::RootRepairReason::Disabled,
            "invalid input and a disabled candidate have distinct refusal reasons");
    auto unmarked = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, false, 0xf400, 0xf41f, 0x840);
    require(unmarked.reason == RaphaelVm::RootRepairReason::TargetUnmarked,
            "an unmarked device records a distinct refusal reason");
    auto reasonFor = [&](uint32_t hub, uint32_t vmid, bool reprogram, uint64_t root,
                         uint32_t base, uint32_t top, uint32_t offset) {
        put32(0, hub); put32(4, vmid); bytes[0x24] = reprogram;
        put64(0x18, root);
        return RaphaelVm::prepareInvalidateInfo(
            bytes, sizeof(bytes), true, true, base, top, offset).reason;
    };
    require(reasonFor(1, 2, true, 0xf401234001ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::WrongHub &&
            reasonFor(0, 3, true, 0xf401234001ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::WrongVmid &&
            reasonFor(0, 2, false, 0xf401234001ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::NotReprogrammed &&
            reasonFor(0, 2, true, 0xf401234001ULL, 0xf400, 0xf3ff, 0x840) ==
                RaphaelVm::RootRepairReason::InvalidAperture &&
            reasonFor(0, 2, true, 0xf401234003ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::SystemRoot &&
            reasonFor(0, 2, true, 0xf401234009ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::UnsupportedFlags &&
            reasonFor(0, 2, true, 0x841234001ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::AlreadyPhysical &&
            reasonFor(0, 2, true, 0x4001234001ULL, 0xf400, 0xf41f, 0x840) ==
                RaphaelVm::RootRepairReason::OutsideFramebuffer,
            "every root-repair refusal has a distinct stable reason");
    require(reasonFor(0, 2, true, 0xf00000000001ULL, 0x0001, 0xffffff, 0xffffff) ==
                RaphaelVm::RootRepairReason::Overflow,
            "a root whose MC-to-physical result exceeds bit 47 is rejected as overflow");
    put32(0, 0); put32(4, 2); bytes[0x24] = 1; put64(0x18, 0xf401234001ULL);

    alignas(uint32_t) unsigned char prepared[0x54] {};
    for (size_t i = 0; i < 0x54 / sizeof(uint32_t); ++i) {
        const uint32_t value = 0x1000u + static_cast<uint32_t>(i);
        std::memcpy(prepared + i * sizeof(uint32_t), &value, sizeof(value));
    }
    local = RaphaelVm::prepareInvalidateInfo(
        bytes, sizeof(bytes), true, true, 0xf400, 0xf41f, 0x840);
    uint32_t nativeRootLo = static_cast<uint32_t>(local.nativeRoot);
    uint32_t nativeRootHi = static_cast<uint32_t>(local.nativeRoot >> 32);
    std::memcpy(prepared + 4, &nativeRootLo, sizeof(nativeRootLo));
    std::memcpy(prepared + 12, &nativeRootHi, sizeof(nativeRootHi));
    auto program = RaphaelVm::observePreparedRequest(
        bytes, sizeof(bytes), local.bytes, sizeof(local.bytes),
        prepared, sizeof(prepared), true, local.repaired, local.reason);
    require(program.valid && program.request.valid && program.request.vmid == 2 &&
                program.alternate,
            "the prepared request remains tied to its source VMID and packet variant");
    require(program.words[0] == 0x1000 && program.words[10] == 0x100a &&
                program.words[20] == 0x1014,
            "all 21 prepared register/value dwords are copied after native encoding");
    require(program.rootRepaired && program.preparedRootMatches &&
                program.nativeRoot == 0x841234001ULL,
            "the observation ties native output to the repaired local root");
    prepared[4] ^= 1;
    auto mismatchedProgram = RaphaelVm::observePreparedRequest(
        bytes, sizeof(bytes), local.bytes, sizeof(local.bytes),
        prepared, sizeof(prepared), true, local.repaired, local.reason);
    require(mismatchedProgram.valid && !mismatchedProgram.preparedRootMatches,
            "native output that does not contain the repaired root is diagnosed");
    prepared[4] ^= 1;
    require(program.infoWords[0] == 0 && program.infoWords[1] == 2 &&
                program.infoWords[9] == 1,
            "all 10 source request dwords are retained without normalization");
    bytes[0x25] = 0xa5;
    bytes[0x26] = 0x5a;
    bytes[0x27] = 0xc3;
    program = RaphaelVm::observePreparedRequest(
        bytes, sizeof(bytes), local.bytes, sizeof(local.bytes),
        prepared, sizeof(prepared), false, local.repaired, local.reason);
    require(program.infoWords[9] == 0xc35aa501,
            "reserved source bytes survive the bounded copy");
    require(!RaphaelVm::observePreparedRequest(
                bytes, sizeof(bytes), local.bytes, sizeof(local.bytes),
                prepared, 0x50, true, local.repaired, local.reason).valid,
            "a truncated prepared request is rejected");

    RaphaelVm::FramebufferAperture aperture {
        0xf400000000ULL, 0xf41fffffffULL, 0x840000000ULL, 0x10000000ULL};
    require(RaphaelVm::physicalTableAddress(0xf401100000ULL, aperture) ==
                0x841100000ULL,
            "non-SYSTEM child page directories convert MC to physical space");
    require(RaphaelVm::physicalTableAddress(0xf401100040ULL, aperture) ==
                0x841100040ULL,
            "64-byte-aligned child page directories retain address bits 11:6");
    require(RaphaelVm::physicalTableAddress(0x841100000ULL, aperture) ==
                0x841100000ULL,
            "already-physical page-directory addresses remain physical");
    require(RaphaelVm::physicalTableAddress(0x400100000ULL, aperture) == 0,
            "VM virtual addresses are never treated as page-directory storage");

    // Control 0x3b encodes depth 1 and block_size - 9 == 7, so its decoded
    // 16-bit leaf geometry is root[64] -> leaf[256/192/512].
    // Child table pointers are deliberately in logical MC space, as Apple's
    // getPDEValue emits them; the walker must convert only those non-leaf pointers.
    alignas(uint64_t) uint64_t pageTables[0x10000 / 8] {};
    auto store = [&](uint64_t physicalAddress, uint64_t value) {
        pageTables[(physicalAddress - aperture.physicalBase) / 8] = value;
    };
    store(0x840000000ULL + 64 * 8, 0xf400002001ULL);
    store(0x840002000ULL + 256 * 8, 0xf401000071ULL);
    store(0x840002000ULL + 192 * 8, 0x123450000077ULL);
    store(0x840002000ULL + 512 * 8, 0xabcde0000071ULL);
    auto reader = [&](uint64_t physicalAddress, uint64_t &value) {
        if (physicalAddress < aperture.physicalBase ||
            physicalAddress + 8 > aperture.physicalBase + sizeof(pageTables)) return false;
        value = pageTables[(physicalAddress - aperture.physicalBase) / 8];
        return true;
    };
    auto walkA = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x400100000ULL, aperture, reader);
    require(walkA.valid && walkA.complete && walkA.count == 2 &&
                walkA.entries[0].index == 64 && walkA.entries[0].childConverted &&
                walkA.entries[1].index == 256 && !walkA.entries[1].childConverted &&
                walkA.entries[1].valid && walkA.entries[1].readable &&
                walkA.entries[1].writeable && walkA.entries[1].executable,
            "multi-level walk converts child PDEs and decodes the final leaf");
    auto walkB = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x4000c0000ULL, aperture, reader);
    require(walkB.valid && walkB.complete && walkB.count == 2 &&
                walkB.entries[0].index == 64 && walkB.entries[1].index == 192 &&
                walkB.entries[1].raw == 0x123450000077ULL,
            "a second VMID2 VA selects its own decoded leaf");
    auto walkC = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x400200000ULL, aperture, reader);
    require(walkC.valid && walkC.complete && walkC.count == 2 &&
                walkC.entries[0].index == 64 && walkC.entries[1].index == 512 &&
                walkC.entries[1].raw == 0xabcde0000071ULL,
            "a 16-bit leaf index is not truncated to the encoded seven bits");

    store(0x840000000ULL + 64 * 8, 0xf400002003ULL);
    auto systemPde = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x400100000ULL, aperture, reader);
    require(systemPde.valid && !systemPde.complete && systemPde.count == 1 &&
                systemPde.entries[0].system,
            "a SYSTEM child PDE is decoded but never followed through BAR0");
    store(0x840000000ULL + 64 * 8,
          0xf401000071ULL | (1ULL << 54));
    auto hugeLeaf = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x400100000ULL, aperture, reader);
    require(hugeLeaf.valid && hugeLeaf.complete && hugeLeaf.count == 1 &&
                hugeLeaf.entries[0].pdeAsPte && !hugeLeaf.entries[0].childConverted,
            "PDE_PTE terminates the walk and its data address is never converted");
    store(0x840000000ULL + 64 * 8, 0xf400002001ULL);
    store(0x840002000ULL + 256 * 8, 0xf401000071ULL | (1ULL << 56));
    auto translateFurther = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x400100000ULL, aperture, reader);
    require(translateFurther.valid && !translateFurther.complete &&
                translateFurther.count == 2 &&
                translateFurther.entries[1].translateFurther,
            "unsupported TRANSLATE_FURTHER leaves remain decoded but incomplete");

    // Encoded block size zero means a 9-bit leaf, not an invalid context:
    // depth 2 is root[16] -> intermediate[0] -> leaf[256].
    store(0x840000000ULL + 16 * 8, 0xf400004001ULL);
    store(0x840004000ULL + 0 * 8, 0xf400005001ULL);
    store(0x840005000ULL + 256 * 8, 0x567890000071ULL);
    auto encodedZero = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x5, 0x400100000ULL, aperture, reader);
    require(encodedZero.valid && encodedZero.complete && encodedZero.count == 3 &&
                encodedZero.entries[0].index == 16 &&
                encodedZero.entries[1].index == 0 &&
                encodedZero.entries[2].index == 256 &&
                encodedZero.entries[2].raw == 0x567890000071ULL,
            "encoded zero walks a 512-entry leaf through 9-bit directories");

    // Depth 3 with decoded block size 10 consumes 9 bits per intermediate:
    // VA 0x30201406000 is root[3] -> intermediate[4] -> intermediate[5] -> leaf[6].
    auto depthThreeReader = [&](uint64_t physicalAddress, uint64_t &value) {
        if (physicalAddress == 0x840000018ULL) value = 0xf400006001ULL;
        else if (physicalAddress == 0x840006020ULL) value = 0xf400007001ULL;
        else if (physicalAddress == 0x840007028ULL) value = 0xf400008001ULL;
        else if (physicalAddress == 0x840008030ULL) value = 0x6789a0000071ULL;
        else return false;
        return true;
    };
    auto depthThree = RaphaelVm::walkPageTables(
        0x840000001ULL, 0xf, 0x30201406000ULL, aperture, depthThreeReader);
    require(depthThree.valid && depthThree.complete && depthThree.count == 4 &&
                depthThree.entries[0].index == 3 &&
                depthThree.entries[1].index == 4 &&
                depthThree.entries[2].index == 5 &&
                depthThree.entries[3].index == 6,
            "depth-three geometry keeps intermediate directories at nine bits");
    unsigned unsupportedGeometryReads = 0;
    auto unsupportedGeometryReader = [&](uint64_t, uint64_t &) {
        ++unsupportedGeometryReads;
        return false;
    };
    auto unsupportedGeometry = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x7f, 0, aperture, unsupportedGeometryReader);
    require(!unsupportedGeometry.valid && unsupportedGeometryReads == 0,
            "a depth-three root shift beyond the 48-bit VA is refused before reading");

    // A root can contain more than 512 entries. The reader intentionally has
    // no entry at root[1], which catches a 9-bit root mask aliasing root[513].
    auto highRootReader = [&](uint64_t physicalAddress, uint64_t &value) {
        if (physicalAddress == 0x840001008ULL) value = 0xf400009001ULL;
        else if (physicalAddress == 0x840009800ULL) value = 0x789ab0000071ULL;
        else return false;
        return true;
    };
    auto highRoot = RaphaelVm::walkPageTables(
        0x840000001ULL, 0x3b, 0x2010100000ULL, aperture, highRootReader);
    require(highRoot.valid && highRoot.complete && highRoot.count == 2 &&
                highRoot.entries[0].index == 513 &&
                highRoot.entries[1].index == 256 &&
                highRoot.entries[1].raw == 0x789ab0000071ULL,
            "the root uses the full high PFN index without a 512-entry alias");

    auto wideFlatIndex = RaphaelVm::walkPageTables(
        0x840000001ULL, 1u, 1ULL << 44, aperture, reader);
    require(!wideFlatIndex.valid,
            "a flat 36-bit PTE index is bounds-checked without uint32 truncation");

    RaphaelVm::FramebufferAperture edge {
        0xf400000000ULL, 0xf40000007fULL, 0x840000000ULL, 0x80ULL};
    require(RaphaelVm::physicalTableAddress(0xf400000040ULL, edge) == 0x840000040ULL &&
                RaphaelVm::physicalTableAddress(0xf400000080ULL, edge) == 0,
            "table translation admits only exact qwords inside the visible BAR boundary");
    unsigned edgeReads = 0;
    auto edgeReader = [&](uint64_t physicalAddress, uint64_t &value) {
        ++edgeReads;
        if (physicalAddress != 0x840000078ULL) return false;
        value = 0x123450000071ULL;
        return true;
    };
    auto lastBarQword = RaphaelVm::walkPageTables(
        0x840000041ULL, 1u, 7ULL << 12, edge, edgeReader);
    require(lastBarQword.valid && lastBarQword.complete && edgeReads == 1,
            "the last complete BAR qword remains readable");
    auto beyondBar = RaphaelVm::walkPageTables(
        0x840000041ULL, 1u, 8ULL << 12, edge, edgeReader);
    require(!beyondBar.valid && edgeReads == 1,
            "a qword starting exactly at the BAR upper edge is refused before reading");

    RaphaelVm::FramebufferAperture reservedBar {
        0xf400000000ULL, 0xf41fffffffULL, 0x840000000ULL, 0x10000000ULL};
    auto reservedReader = [&](uint64_t physicalAddress, uint64_t &value) {
        if (physicalAddress != 0x84fdfc000ULL) return false;
        value = 0x841000071ULL;
        return true;
    };
    auto reservedRoot = RaphaelVm::walkPageTables(
        0x84fdfc001ULL, 1u, 0, reservedBar, reservedReader);
    require(reservedRoot.valid && reservedRoot.complete && reservedRoot.count == 1 &&
                reservedRoot.entries[0].tablePhysical == 0x84fdfc000ULL,
            "the GART root in the reserved final 16 MiB remains walkable");
    require(RaphaelVm::physicalTableAddress(0x850000000ULL, reservedBar) == 0,
            "the first address beyond the 256 MiB BAR remains inaccessible");

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
    constexpr uint32_t gc = 0x1260;
    constexpr auto sem2 = RaphaelVm::decodeInvalidateRegister(
        gc + 0x160f, gc + 0x160d, gc + 0x161f, gc + 0x1631);
    constexpr auto req7 = RaphaelVm::decodeInvalidateRegister(
        gc + 0x1626, gc + 0x160d, gc + 0x161f, gc + 0x1631);
    constexpr auto ack17 = RaphaelVm::decodeInvalidateRegister(
        gc + 0x1642, gc + 0x160d, gc + 0x161f, gc + 0x1631);
    constexpr auto outside = RaphaelVm::decodeInvalidateRegister(
        gc + 0x1643, gc + 0x160d, gc + 0x161f, gc + 0x1631);
    require(sem2.valid && sem2.kind == RaphaelVm::InvalidateRegisterKind::Semaphore &&
                sem2.engine == 2 && req7.valid &&
                req7.kind == RaphaelVm::InvalidateRegisterKind::Request &&
                req7.engine == 7 && ack17.valid &&
                ack17.kind == RaphaelVm::InvalidateRegisterKind::Acknowledge &&
                ack17.engine == 17 && !outside.valid,
            "prepared register numbers identify the actual invalidate engine and role");
    uint32_t invalidateReadCount = 0;
    uint32_t lastInvalidateRead = 0;
    const auto invalidateReader = [&](uint32_t reg) {
        ++invalidateReadCount;
        lastInvalidateRead = reg;
        return reg ^ 0x55aa55aau;
    };
    const auto semSample = RaphaelVm::sampleInvalidateRegister(
        gc + 0x160f, sem2, invalidateReader);
    require(!semSample.read && semSample.value == 0 && invalidateReadCount == 0,
            "sampling a semantic invalidate semaphore never invokes the MMIO reader");
    const auto reqSample = RaphaelVm::sampleInvalidateRegister(
        gc + 0x1626, req7, invalidateReader);
    const auto ackSample = RaphaelVm::sampleInvalidateRegister(
        gc + 0x1642, ack17, invalidateReader);
    require(reqSample.read && ackSample.read && invalidateReadCount == 2 &&
                lastInvalidateRead == gc + 0x1642 &&
                reqSample.value == ((gc + 0x1626) ^ 0x55aa55aau) &&
                ackSample.value == ((gc + 0x1642) ^ 0x55aa55aau),
            "request and acknowledge diagnostics retain ordinary MMIO reads");
    require(RaphaelVm::decodeFaultAddress(0x12345, 0xfffffff4) ==
                0x400012345000ULL,
            "the 36-bit fault page number is masked and converted to a byte VA");

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

    {
        uint64_t out = 0;
        require(RaphaelVm::convertEntryAddress(0xf40b6f3000ULL, false, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::Converted && out == 0x84b6f3000ULL,
                "a framebuffer MC table address converts to the physical carve-out form");
        require(RaphaelVm::convertEntryAddress(0xf41fffffffULL, false, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::Converted && out == 0x85fffffffULL,
                "the last MC aperture byte converts to the last carve-out byte");
        require(RaphaelVm::convertEntryAddress(0x84b6f3000ULL, false, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::AlreadyPhysical && out == 0x84b6f3000ULL,
                "a physical carve-out address is never converted twice");
        require(RaphaelVm::convertEntryAddress(0xf40b6f3000ULL, true, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::System && out == 0xf40b6f3000ULL,
                "a SYSTEM entry keeps its guest physical address");
        require(RaphaelVm::convertEntryAddress(0x12345000ULL, false, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::Outside && out == 0x12345000ULL,
                "an address outside both apertures passes through");
        require(RaphaelVm::convertEntryAddress(0xf420000000ULL, false, 0xf400, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::Outside,
                "the first byte above the MC aperture is outside");
        require(RaphaelVm::convertEntryAddress(0xf40b6f3000ULL, false, 0, 0xf41f,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::InvalidAperture && out == 0xf40b6f3000ULL,
                "an unpublished aperture never converts");
        require(RaphaelVm::convertEntryAddress(0xf40b6f3000ULL, false, 0xf400, 0xf3ff,
                                               0x840, out) ==
                    RaphaelVm::EntryDomain::InvalidAperture,
                "an inverted aperture never converts");
        require(RaphaelVm::convertEntryAddress(0xf40b6f3000ULL, false, 0xf400, 0xf41f,
                                               0x1840, out) ==
                    RaphaelVm::EntryDomain::Converted && out == 0x184b6f3000ULL,
                "conversion follows the published physical offset, not a constant");
    }

    std::puts("GPU VM diagnostic fixtures passed");
}
