#pragma once

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace RaphaelTextureDiag {

using ReadFn = bool (*)(void *context, uint64_t address, void *out, size_t size);

struct Result {
    bool found {};
    bool uuidMatch {};
    bool pathTerminated {};
    bool instructionMatch {};
    bool alreadyPatched {};
    uint64_t textBase {};
    uint64_t instructionAddress {};
    uint32_t imageCount {};
    uint32_t inspected {};
    uint32_t status {};
};

struct Target {
    const char *driverPath;
    size_t pathSize;
    const uint8_t *uuid;
    uint64_t instructionOffset;
    const uint8_t *instruction;
    const uint8_t *patchedInstruction;
    size_t instructionSize;
};

enum : uint32_t {
    Ok = 0,
    BadReader = 1,
    BadAllImageInfo = 2,
    BadCount = 3,
    BadImage = 4,
    BadMachHeader = 5,
    BadLoadCommands = 6,
    BadPath = 7,
    BadUuid = 8,
    BadText = 9,
    BadInstruction = 10,
};

static constexpr uint32_t kMaxImages = 2048;
static constexpr size_t kMaxLoadCommands = 16 * 1024;
static constexpr char kDriverPath[] =
    "/System/Library/Extensions/AMDRadeonX6000MTLDriver.bundle/Contents/MacOS/"
    "AMDRadeonX6000MTLDriver";
static constexpr uint64_t kInstructionOffset = 0x13a7e1;
static constexpr uint8_t kUuid[16] = {
    0x90, 0x6f, 0x11, 0xa3, 0x9d, 0xaf, 0x35, 0xbd,
    0xb8, 0xea, 0xcf, 0xd2, 0x16, 0x0f, 0xae, 0x1a
};
static constexpr uint8_t kPatchedInstruction[10] = {
    0x48, 0xb8, 0x00, 0x00, 0x70, 0xf7, 0x01, 0x00, 0x00, 0x00
};
static constexpr uint8_t kInstruction[10] = {
    0x48, 0xb8, 0x00, 0x00, 0x70, 0xff, 0x01, 0x00, 0x00, 0x00
};
static constexpr Target kTextureTarget = {
    kDriverPath, sizeof(kDriverPath), kUuid, kInstructionOffset,
    kInstruction, kPatchedInstruction, sizeof(kInstruction)
};
static constexpr char kVcnDpmDriverPath[] =
    "/System/Library/Extensions/AMDRadeonVADriver2.bundle/Contents/MacOS/AMDRadeonVADriver2";
static constexpr uint8_t kVcnDpmUuid[16] = {
    0x81, 0xdf, 0x72, 0x15, 0x43, 0xe2, 0x3b, 0xa1,
    0xbe, 0x2d, 0xef, 0xb1, 0xc5, 0x08, 0xb8, 0x1a
};
static constexpr uint8_t kVcnDpmInstruction[8] = {0x55, 0x48, 0x89, 0xe5, 0xb0, 0x01, 0x5d, 0xc3};
static constexpr uint8_t kVcnDpmPatchedInstruction[8] = {0x55, 0x48, 0x89, 0xe5, 0xb0, 0x00, 0x5d, 0xc3};
static constexpr Target kVcnDpmTarget = {
    kVcnDpmDriverPath, sizeof(kVcnDpmDriverPath), kVcnDpmUuid, 0x3d5f6,
    kVcnDpmInstruction, kVcnDpmPatchedInstruction, sizeof(kVcnDpmInstruction)
};

inline uint32_t u32(const uint8_t *p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) |
           (uint32_t(p[3]) << 24);
}

inline uint64_t u64(const uint8_t *p) {
    return uint64_t(u32(p)) | (uint64_t(u32(p + 4)) << 32);
}

inline bool addOk(uint64_t a, uint64_t b, uint64_t *out) {
    if (b > UINT64_MAX - a) return false;
    *out = a + b;
    return true;
}

inline bool boundedRead(ReadFn read, void *context, uint64_t address, void *out, size_t size) {
    return address != 0 && address < 0x800000000000ULL && size != 0 &&
           size <= 0x800000000000ULL - address && read(context, address, out, size);
}

inline Result inspect(ReadFn read, void *context, uint64_t allImageInfoAddress,
                      uint32_t allImageInfoFormat, const Target &target = kTextureTarget) {
    Result result {};
    if (read == nullptr || allImageInfoAddress == 0) {
        result.status = BadReader;
        return result;
    }
    if (target.driverPath == nullptr || target.uuid == nullptr ||
        target.instruction == nullptr || target.patchedInstruction == nullptr ||
        target.pathSize == 0 || target.pathSize > 256 || target.instructionSize == 0 ||
        target.instructionSize > 16) {
        result.status = BadPath;
        return result;
    }
    // dyld_all_image_infos: version, count, infoArray (64-bit format).
    uint8_t infos[16] {};
    if (allImageInfoFormat != 1 || !boundedRead(read, context, allImageInfoAddress, infos, sizeof(infos))) {
        result.status = BadAllImageInfo;
        return result;
    }
    const uint32_t count = u32(infos + 4);
    const uint64_t array = u64(infos + 8);
    result.imageCount = count;
    if (count == 0 || count > kMaxImages || array == 0) {
        result.status = BadCount;
        return result;
    }
    for (uint32_t i = 0; i < count; ++i) {
        uint64_t entryAddress = 0;
        if (!addOk(array, uint64_t(i) * 24, &entryAddress)) break;
        uint8_t image[24] {};
        ++result.inspected;
        if (!boundedRead(read, context, entryAddress, image, sizeof(image))) continue;
        const uint64_t loadAddress = u64(image);
        const uint64_t pathAddress = u64(image + 8);
        if (loadAddress == 0 || pathAddress == 0) continue;
        char path[256] {};
        if (!boundedRead(read, context, pathAddress, path, target.pathSize)) continue;
        if (memcmp(path, target.driverPath, target.pathSize) != 0) continue;
        result.pathTerminated = true;
        uint8_t header[32] {};
        if (!boundedRead(read, context, loadAddress, header, sizeof(header)) ||
            u32(header) != 0xfeedfacf || u32(header + 4) != 0x01000007 ||
            (u32(header + 8) & 0x00ffffff) != 8 || u32(header + 16) == 0 ||
            u32(header + 16) > u32(header + 20) / 8 ||
            u32(header + 20) > kMaxLoadCommands) { result.status = BadMachHeader; return result; }
        const uint32_t ncmds = u32(header + 16);
        const uint32_t sizeofcmds = u32(header + 20);
        uint8_t *commands = new uint8_t[sizeofcmds];
        uint64_t commandsAddress = 0;
        if (commands == nullptr || !addOk(loadAddress, 32, &commandsAddress) ||
            !boundedRead(read, context, commandsAddress, commands, sizeofcmds)) {
            delete [] commands;
            continue;
        }
        bool uuid = false, text = false;
        unsigned uuidCount = 0, textCount = 0;
        uint64_t textBase = 0;
        size_t offset = 0;
        bool malformed = false;
        for (uint32_t command = 0; command < ncmds; ++command) {
            if (offset > sizeofcmds || sizeofcmds - offset < 8) { malformed = true; break; }
            const uint8_t *cmd = commands + offset;
            const uint32_t type = u32(cmd);
            const uint32_t size = u32(cmd + 4);
            if (size < 8 || size > sizeofcmds - offset) { malformed = true; break; }
            if (type == 0x1b && size >= 24) {
                ++uuidCount;
                    uuid = memcmp(cmd + 8, target.uuid, 16) == 0;
            } else if (type == 0x19 && size >= 72) {
                char name[17] {};
                memcpy(name, cmd + 8, 16);
                if (strcmp(name, "__TEXT") == 0) {
                    ++textCount;
                    const uint64_t vmsize = u64(cmd + 32);
                    if (target.instructionOffset <= vmsize &&
                        target.instructionSize <= vmsize - target.instructionOffset) {
                        textBase = loadAddress;
                        text = true;
                    }
                }
            }
            offset += size;
        }
        result.uuidMatch = uuid;
        result.textBase = textBase;
        delete [] commands;
        if (malformed || offset != sizeofcmds || uuidCount > 1 || textCount > 1) { result.status = BadLoadCommands; return result; }
        if (!uuid) { result.status = BadUuid; return result; }
        if (!text || !addOk(textBase, target.instructionOffset, &result.instructionAddress)) {
            result.status = BadText;
            return result;
        }
        uint8_t instruction[16] {};
        const bool readOk = boundedRead(read, context, result.instructionAddress,
                                        instruction, target.instructionSize);
        result.instructionMatch = readOk &&
                                  memcmp(instruction, target.instruction, target.instructionSize) == 0;
        result.alreadyPatched = readOk &&
                               memcmp(instruction, target.patchedInstruction, target.instructionSize) == 0;
        result.found = true;
        result.status = (result.instructionMatch || result.alreadyPatched) ? Ok : BadInstruction;
        return result;
    }
    result.status = BadImage;
    return result;
}

} // namespace RaphaelTextureDiag
