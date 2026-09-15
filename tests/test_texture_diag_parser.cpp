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

}
