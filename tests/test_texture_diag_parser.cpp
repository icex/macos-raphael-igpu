#include "../src/TextureDiagParser.hpp"

#include <cassert>
#include <cstring>
#include <vector>

struct Fixture {
    std::vector<unsigned char> bytes = std::vector<unsigned char>(2 * 1024 * 1024);
    uint64_t base() const { return reinterpret_cast<uint64_t>(bytes.data()); }
    bool read(uint64_t address, void *out, size_t size) {
        if (address < base() || address - base() > bytes.size() ||
            size > bytes.size() - static_cast<size_t>(address - base())) return false;
        std::memcpy(out, bytes.data() + (address - base()), size);
        return true;
    }
};

static bool readFixture(void *context, uint64_t address, void *out, size_t size) {
    return static_cast<Fixture *>(context)->read(address, out, size);
}

template <typename T>
static void put(Fixture &f, size_t offset, T value) {
    std::memcpy(f.bytes.data() + offset, &value, sizeof(value));
}

static void makeValid(Fixture &f, bool wrongUuid = false) {
    const uint64_t all = f.base() + 0x100;
    const uint64_t array = f.base() + 0x200;
    const uint64_t image = f.base() + 0x400;
    const uint64_t path = f.base() + 0x500;
    const uint64_t text = image;
    put<uint32_t>(f, 0x100, 1);
    put<uint32_t>(f, 0x104, 1);
    put<uint64_t>(f, 0x108, array);
    put<uint64_t>(f, 0x200, image);
    put<uint64_t>(f, 0x208, path);
    std::strcpy(reinterpret_cast<char *>(f.bytes.data() + 0x500),
                RaphaelTextureDiag::kDriverPath);
    put<uint32_t>(f, 0x400, 0xfeedfacf);
    put<uint32_t>(f, 0x404, 0x01000007);
    put<uint32_t>(f, 0x408, 8);
    put<uint32_t>(f, 0x410, 2);
    put<uint32_t>(f, 0x414, 96);
    put<uint32_t>(f, 0x420, 0x1b);
    put<uint32_t>(f, 0x424, 24);
    static const uint8_t uuid[] = {0x90,0x6f,0x11,0xa3,0x9d,0xaf,0x35,0xbd,
                                   0xb8,0xea,0xcf,0xd2,0x16,0x0f,0xae,0x1a};
    std::memcpy(f.bytes.data() + 0x428, uuid, sizeof(uuid));
    if (wrongUuid) f.bytes[0x428] ^= 1;
    put<uint32_t>(f, 0x438, 0x19);
    put<uint32_t>(f, 0x43c, 72);
    std::memcpy(f.bytes.data() + 0x440, "__TEXT", 6);
    put<uint64_t>(f, 0x450, 0x7ffb08bf3000ULL);
    put<uint64_t>(f, 0x458, 0x5029aeULL);
    static const uint8_t instruction[] = {0x48,0xb8,0x00,0x00,0x70,0xff,0x01,0x00,0x00,0x00};
    std::memcpy(reinterpret_cast<void *>(text + RaphaelTextureDiag::kInstructionOffset),
                instruction, sizeof(instruction));
    (void)all;
}

static void makeVcnValid(Fixture &f, bool wrongUuid = false) {
    makeValid(f);
    std::memset(f.bytes.data() + 0x500, 0, RaphaelTextureDiag::kVcnDpmTarget.pathSize);
    std::memcpy(f.bytes.data() + 0x500, RaphaelTextureDiag::kVcnDpmDriverPath,
                RaphaelTextureDiag::kVcnDpmTarget.pathSize);
    std::memcpy(f.bytes.data() + 0x428, RaphaelTextureDiag::kVcnDpmUuid, 16);
    if (wrongUuid) f.bytes[0x428] ^= 1;
    std::memcpy(f.bytes.data() + 0x400 + RaphaelTextureDiag::kVcnDpmTarget.instructionOffset,
                RaphaelTextureDiag::kVcnDpmInstruction,
                RaphaelTextureDiag::kVcnDpmTarget.instructionSize);
}

int main() {
    {
        size_t offset=99, size=99;
        assert(RaphaelTextureDiag::patchSpan(RaphaelTextureDiag::kTextureTarget,offset,size));
        assert(offset==5 && size==1);
        assert(RaphaelTextureDiag::patchSpan(RaphaelTextureDiag::kVcnDpmTarget,offset,size));
        assert(offset==5 && size==1);
        assert(RaphaelTextureDiag::patchSpan(RaphaelTextureDiag::kFeedbackTarget,offset,size));
        assert(offset==2 && size==3);
        Fixture f; makeValid(f);
        auto &target=RaphaelTextureDiag::kFeedbackTarget;
        std::memcpy(f.bytes.data()+0x400+target.instructionOffset,target.instruction,target.instructionSize);
        auto check=[&](){ return RaphaelTextureDiag::inspect(readFixture,&f,f.base()+0x100,1,target); };
        assert(check().instructionMatch && !check().alreadyPatched);
        std::memcpy(f.bytes.data()+0x400+target.instructionOffset+offset,target.patchedInstruction+offset,size);
        assert(check().status==RaphaelTextureDiag::Ok && check().alreadyPatched);
        f.bytes[0x400+target.instructionOffset+7]^=1;
        assert(!check().instructionMatch);
    }

    Fixture valid;
    makeValid(valid);
    auto result = RaphaelTextureDiag::inspect(readFixture, &valid,
                                               valid.base() + 0x100, 1);
    assert(result.found && result.uuidMatch && result.instructionMatch &&
           result.status == RaphaelTextureDiag::Ok);

    Fixture malformed;
    makeValid(malformed);
    put<uint32_t>(malformed, 0x104, RaphaelTextureDiag::kMaxImages + 1);
    result = RaphaelTextureDiag::inspect(readFixture, &malformed,
                                         malformed.base() + 0x100, 1);
    assert(!result.found && result.status == RaphaelTextureDiag::BadCount);

    Fixture wrongUuid;
    makeValid(wrongUuid, true);
    result = RaphaelTextureDiag::inspect(readFixture, &wrongUuid,
                                         wrongUuid.base() + 0x100, 1);
    assert(!result.found && !result.uuidMatch && result.status == RaphaelTextureDiag::BadUuid);
    auto inspect = [](Fixture &f) {
        return RaphaelTextureDiag::inspect(readFixture, &f, f.base() + 0x100, 1);
    };
    Fixture f;
    makeValid(f);
    put<uint64_t>(f, 0x458, RaphaelTextureDiag::kInstructionOffset + 9);
    assert(inspect(f).status == RaphaelTextureDiag::BadText);
    makeValid(f);
    put<uint32_t>(f, 0x43c, 71);
    assert(inspect(f).status == RaphaelTextureDiag::BadLoadCommands);
    makeValid(f);
    put<uint32_t>(f, 0x410, 3);
    assert(inspect(f).status == RaphaelTextureDiag::BadLoadCommands);
    makeValid(f);
    put<uint32_t>(f, 0x414, 97);
    assert(inspect(f).status == RaphaelTextureDiag::BadLoadCommands);
    makeValid(f);
    put<uint32_t>(f, 0x404, 7);
    assert(inspect(f).status == RaphaelTextureDiag::BadMachHeader);
    makeValid(f);
    put<uint64_t>(f, 0x208, UINT64_MAX - 8);
    assert(!inspect(f).found);
    makeValid(f);
    put<uint64_t>(f, 0x108, 0xffff800000000000ULL);
    assert(!inspect(f).found);
    makeValid(f);
    f.bytes[0x400 + RaphaelTextureDiag::kInstructionOffset + 5] = 0xf7;
    assert(inspect(f).status == RaphaelTextureDiag::Ok && inspect(f).alreadyPatched &&
           !inspect(f).instructionMatch);
    f.bytes[0x400 + RaphaelTextureDiag::kInstructionOffset + 6] ^= 1;
    assert(inspect(f).status == RaphaelTextureDiag::BadInstruction && !inspect(f).alreadyPatched);
    makeValid(f);
    f.bytes[0x500 + sizeof(RaphaelTextureDiag::kDriverPath) - 1] = 'X';
    assert(!inspect(f).found && !inspect(f).pathTerminated);

    Fixture vcn;
    makeVcnValid(vcn);
    result = RaphaelTextureDiag::inspect(readFixture, &vcn, vcn.base() + 0x100, 1,
                                         RaphaelTextureDiag::kVcnDpmTarget);
    assert(result.found && result.uuidMatch && result.instructionMatch &&
           result.status == RaphaelTextureDiag::Ok);
    Fixture vcnWrongUuid;
    makeVcnValid(vcnWrongUuid, true);
    result = RaphaelTextureDiag::inspect(readFixture, &vcnWrongUuid,
                                         vcnWrongUuid.base() + 0x100, 1,
                                         RaphaelTextureDiag::kVcnDpmTarget);
    assert(!result.found && result.status == RaphaelTextureDiag::BadUuid);
    makeVcnValid(vcn);
    vcn.bytes[0x400 + RaphaelTextureDiag::kVcnDpmTarget.instructionOffset + 6] ^= 1;
    result = RaphaelTextureDiag::inspect(readFixture, &vcn, vcn.base() + 0x100, 1,
                                         RaphaelTextureDiag::kVcnDpmTarget);
    assert(result.status == RaphaelTextureDiag::BadInstruction);
    makeVcnValid(vcn);
    std::memcpy(vcn.bytes.data() + 0x400 + RaphaelTextureDiag::kVcnDpmTarget.instructionOffset,
                RaphaelTextureDiag::kVcnDpmPatchedInstruction,
                RaphaelTextureDiag::kVcnDpmTarget.instructionSize);
    result = RaphaelTextureDiag::inspect(readFixture, &vcn, vcn.base() + 0x100, 1,
                                         RaphaelTextureDiag::kVcnDpmTarget);
    assert(result.found && result.alreadyPatched && result.status == RaphaelTextureDiag::Ok);
    auto crossed = RaphaelTextureDiag::kVcnDpmTarget;
    crossed.instructionOffset = 0x5029ae;
    result = RaphaelTextureDiag::inspect(readFixture, &vcn, vcn.base() + 0x100, 1, crossed);
    assert(result.status == RaphaelTextureDiag::BadText);

    // candidate 284: three RENCODE_IB_OP_SET_BALANCE_ENCODING_MODE (0x01000007) targets
    // in the same AMDRadeonVADriver2 image as kVcnDpmTarget.
    {
        const RaphaelTextureDiag::Target *presetTargets[] = {
            &RaphaelTextureDiag::kVcnPresetValueTarget,
            &RaphaelTextureDiag::kVcnPresetHevcGateTarget,
            &RaphaelTextureDiag::kVcnPresetAvcGateTarget,
        };
        for (auto *t : presetTargets) {
            assert(t->driverPath == RaphaelTextureDiag::kVcnDpmTarget.driverPath);
            assert(t->pathSize == RaphaelTextureDiag::kVcnDpmTarget.pathSize);
            assert(t->uuid == RaphaelTextureDiag::kVcnDpmTarget.uuid);
        }

        // Exact TEXT offsets verified against the decompiled asm and the raw
        // Mach-O (file offset = address - __TEXT vmaddr + __TEXT fileoff).
        assert(RaphaelTextureDiag::kVcnPresetValueTarget.instructionOffset == 0x4d458);
        assert(RaphaelTextureDiag::kVcnPresetHevcGateTarget.instructionOffset == 0x4dd74);
        assert(RaphaelTextureDiag::kVcnPresetAvcGateTarget.instructionOffset == 0x4d88c);

        // Vcn3EncCommand::addPresetEncodeModePacket: original load+range-check
        // replaced by an unconditional mov esi,0x01000007 + 9-byte NOP.
        static const uint8_t presetValueOriginal[14] = {
            0x8b, 0x77, 0x30, 0x8d, 0x86, 0xfa, 0xff, 0xff, 0xfe, 0x83, 0xf8, 0x02, 0x77, 0x0a
        };
        static const uint8_t presetValuePatched[14] = {
            0xbe, 0x07, 0x00, 0x00, 0x01, 0x66, 0x0f, 0x1f, 0x84, 0x00, 0x00, 0x00, 0x00, 0x00
        };
        assert(RaphaelTextureDiag::kVcnPresetValueTarget.instructionSize == 14);
        assert(std::memcmp(RaphaelTextureDiag::kVcnPresetValueTarget.instruction,
                            presetValueOriginal, 14) == 0);
        assert(std::memcmp(RaphaelTextureDiag::kVcnPresetValueTarget.patchedInstruction,
                            presetValuePatched, 14) == 0);
        size_t offset = 99, size = 99;
        assert(RaphaelTextureDiag::patchSpan(RaphaelTextureDiag::kVcnPresetValueTarget, offset, size));
        assert(offset == 0 && size == 14);

        // Vcn3EncHevcCommand::buildGeneralCommand / Vcn3EncAvcCommand::buildGeneralCommand:
        // cmp byte [r12+0x1c],1; jnz +0xb -> jnz replaced with two NOPs, same 8 bytes
        // at both sites.
        static const uint8_t gateOriginal[8] = {0x41, 0x80, 0x7c, 0x24, 0x1c, 0x01, 0x75, 0x0b};
        static const uint8_t gatePatched[8] = {0x41, 0x80, 0x7c, 0x24, 0x1c, 0x01, 0x90, 0x90};
        for (auto *t : {&RaphaelTextureDiag::kVcnPresetHevcGateTarget,
                        &RaphaelTextureDiag::kVcnPresetAvcGateTarget}) {
            assert(t->instructionSize == 8);
            assert(std::memcmp(t->instruction, gateOriginal, 8) == 0);
            assert(std::memcmp(t->patchedInstruction, gatePatched, 8) == 0);
            offset = 99; size = 99;
            assert(RaphaelTextureDiag::patchSpan(*t, offset, size));
            assert(offset == 6 && size == 2);
        }
        assert(RaphaelTextureDiag::kVcnPresetHevcGateTarget.instructionOffset !=
               RaphaelTextureDiag::kVcnPresetAvcGateTarget.instructionOffset);
    }

    // inspect() round trip for each new target, reusing the VCN image identity fixture.
    {
        const RaphaelTextureDiag::Target *presetTargets[] = {
            &RaphaelTextureDiag::kVcnPresetValueTarget,
            &RaphaelTextureDiag::kVcnPresetHevcGateTarget,
            &RaphaelTextureDiag::kVcnPresetAvcGateTarget,
        };
        for (auto *t : presetTargets) {
            Fixture preset;
            makeVcnValid(preset);
            std::memcpy(preset.bytes.data() + 0x400 + t->instructionOffset,
                        t->instruction, t->instructionSize);
            auto presetResult = RaphaelTextureDiag::inspect(readFixture, &preset,
                                                            preset.base() + 0x100, 1, *t);
            assert(presetResult.found && presetResult.uuidMatch &&
                   presetResult.instructionMatch &&
                   presetResult.status == RaphaelTextureDiag::Ok);

            std::memcpy(preset.bytes.data() + 0x400 + t->instructionOffset,
                        t->patchedInstruction, t->instructionSize);
            presetResult = RaphaelTextureDiag::inspect(readFixture, &preset,
                                                       preset.base() + 0x100, 1, *t);
            assert(presetResult.found && presetResult.alreadyPatched &&
                   presetResult.status == RaphaelTextureDiag::Ok);

            std::memcpy(preset.bytes.data() + 0x400 + t->instructionOffset,
                        t->instruction, t->instructionSize);
            preset.bytes[0x400 + t->instructionOffset] ^= 0xff;
            presetResult = RaphaelTextureDiag::inspect(readFixture, &preset,
                                                       preset.base() + 0x100, 1, *t);
            assert(presetResult.status == RaphaelTextureDiag::BadInstruction &&
                   !presetResult.instructionMatch && !presetResult.alreadyPatched);
        }
    }
    // candidate 285: CoreDisplay virtual-display refresh (98-byte window, shared cache image).
    {
        const auto &t = RaphaelTextureDiag::kVirtualDisplayRefreshTarget;
        assert(t.instructionOffset == 0x371de && t.instructionSize == 98);
        assert(t.instructionSize <= RaphaelTextureDiag::kMaxInstructionSize);
        size_t offset = 99, size = 99;
        assert(RaphaelTextureDiag::patchSpan(t, offset, size));
        assert(offset == 0 && size == 96);   // the trailing "00 00" is shared
        // The rip-relative mulsd/addsd (bytes 12..27) must stay at their original addresses.
        assert(std::memcmp(t.instruction + 12, t.patchedInstruction + 12, 16) == 0);
        Fixture cd;
        makeValid(cd);
        std::memset(cd.bytes.data() + 0x500, 0, t.pathSize);
        std::memcpy(cd.bytes.data() + 0x500, RaphaelTextureDiag::kCoreDisplayPath, t.pathSize);
        std::memcpy(cd.bytes.data() + 0x428, RaphaelTextureDiag::kCoreDisplayUuid, 16);
        std::memcpy(cd.bytes.data() + 0x400 + t.instructionOffset, t.instruction, t.instructionSize);
        auto inspect = [&]() {
            return RaphaelTextureDiag::inspect(readFixture, &cd, cd.base() + 0x100, 1, t);
        };
        auto r = inspect();
        assert(r.found && r.uuidMatch && r.instructionMatch && !r.alreadyPatched &&
               r.status == RaphaelTextureDiag::Ok);
        std::memcpy(cd.bytes.data() + 0x400 + t.instructionOffset, t.patchedInstruction,
                    t.instructionSize);
        r = inspect();
        assert(r.found && r.alreadyPatched && r.status == RaphaelTextureDiag::Ok);
        cd.bytes[0x400 + t.instructionOffset + 97] ^= 0xff;   // last byte of the window
        r = inspect();
        assert(r.status == RaphaelTextureDiag::BadInstruction && !r.instructionMatch &&
               !r.alreadyPatched);
    }
}
