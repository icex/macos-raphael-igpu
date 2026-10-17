#pragma once

// Structural locator for AMD_DeviceSettings boolean flags in Apple's
// AMDRadeonX6000MTLDriver, used to clear enableTexturePipeBankXor on Raphael.
//
// The first delivery pinned the driver UUID, the __TEXT offset 0x13a7e1 and the exact
// instruction bytes, so any OS update turned the correction into a silent no-op. This
// locator instead derives everything from the image:
//
//   1. the bit index comes from the driver's own Objective-C type metadata, which encodes
//      AMD_DeviceSettings as an ordered run of one-bit fields;
//   2. the patch site is found by instruction *shape*, not address:
//
//          48 b8 <imm64>    movabs r64, imm64      (the default-enabled mask)
//          48 09 /r         or     r64, r64        (merge the computed bits)
//          48 89 /r         mov    [rdi], r64      (store into the settings object)
//
//      restricted to immediates that actually have the target bit set.
//
// Both encodings are fixed-length, so no disassembler is required and this can run in the
// kernel. The locator is fail-closed: it patches only when exactly one candidate matches.
// A recompile that moves code, renumbers unrelated flags or changes the default mask is
// tolerated; a change to this constructor shape is refused rather than guessed at.

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace RaphaelTextureSetting {

enum : uint32_t {
    Ok = 0,
    NoMetadata = 1,       // no {AMD_DeviceSettings=...} run found
    BadMetadata = 2,      // malformed, duplicated or oversized bitfield encoding
    FieldAbsent = 3,      // the requested flag is not in the layout
    FieldNotBoolean = 4,  // the flag is present but not a single bit
    FieldTooWide = 5,     // the flag lies outside the first 64-bit word
    LayoutConflict = 6,   // two AMD_DeviceSettings runs disagree on the index
    NoCandidate = 7,      // the constructor shape was not found
    Ambiguous = 8,        // more than one candidate; refuse rather than guess
};

struct Site {
    uint32_t status {NoCandidate};
    uint32_t bit {};                 // bit index within the settings word
    uint32_t candidates {};          // how many shapes matched (1 == usable)
    uint64_t instructionOffset {};   // offset of the movabs within the scanned text
    uint64_t byteOffset {};          // offset of the byte that carries the bit
    uint8_t  bitInByte {};           // bit position inside that byte
    uint8_t  currentByte {};         // the byte as found
    uint8_t  patchedByte {};         // the byte with the flag cleared
    uint64_t immediate {};           // the full default mask, for logging
    bool     alreadyClear {};        // the flag is already disabled in this image
};

// Longest field name we will consider; the real encoding is far below this.
static constexpr size_t kMaxFieldName = 64;
// A boolean flag must live in the first 64-bit word to be reachable by one movabs.
static constexpr uint32_t kWordBits = 64;

inline uint64_t readU64LE(const uint8_t *p) {
    uint64_t value = 0;
    for (int i = 7; i >= 0; --i) value = (value << 8) | uint64_t(p[i]);
    return value;
}

inline bool isRexW(uint8_t byte) {
    // REX.W with any combination of R/X/B.
    return byte == 0x48 || byte == 0x49 || byte == 0x4c || byte == 0x4d;
}

/// Parse one `{AMD_DeviceSettings="name"b1"name"b1...}` run, returning the bit index of
/// `field`. Widths accumulate so unrelated flags may be added or renumbered upstream.
inline uint32_t bitFromLayout(const uint8_t *blob, size_t size, size_t start,
                              const char *field, uint32_t *bitOut, bool *foundOut) {
    size_t p = start;
    uint32_t bit = 0;
    bool found = false;
    uint32_t foundBit = 0;
    const size_t fieldLength = strnlen(field, kMaxFieldName);
    // Reject a layout that repeats a name: that means we mis-parsed it.
    uint32_t fields = 0;
    while (p < size) {
        if (blob[p] != '"') break;
        const size_t nameStart = ++p;
        while (p < size && blob[p] != '"' && blob[p] != '\0') ++p;
        if (p >= size || blob[p] != '"') return BadMetadata;
        const size_t nameLength = p - nameStart;
        ++p;
        if (nameLength == 0 || nameLength > kMaxFieldName) return BadMetadata;
        if (p >= size || blob[p] != 'b') break;  // not a bitfield: end of the run
        ++p;
        if (p >= size || blob[p] < '0' || blob[p] > '9') return BadMetadata;
        uint32_t width = 0;
        while (p < size && blob[p] >= '0' && blob[p] <= '9') {
            width = width * 10 + uint32_t(blob[p] - '0');
            if (width > kWordBits) return BadMetadata;
            ++p;
        }
        if (width < 1) return BadMetadata;
        if (++fields > 4096) return BadMetadata;
        if (nameLength == fieldLength && memcmp(blob + nameStart, field, fieldLength) == 0) {
            if (found) return BadMetadata;   // duplicate name in one layout
            if (width != 1) return FieldNotBoolean;
            found = true;
            foundBit = bit;
        }
        if (bit > UINT32_MAX - width) return BadMetadata;
        bit += width;
    }
    *bitOut = foundBit;
    *foundOut = found;
    return Ok;
}

/// Derive the bit index of `field` from the driver's `__objc_methtype` section.
inline uint32_t deriveBit(const uint8_t *methtype, size_t size, const char *field,
                          uint32_t *bitOut) {
    static const char kMarker[] = "{AMD_DeviceSettings=";
    const size_t markerLength = sizeof(kMarker) - 1;
    if (methtype == nullptr || size < markerLength) return NoMetadata;
    bool sawLayout = false, any = false, agreed = false;
    uint32_t agreedBit = 0;
    for (size_t i = 0; i + markerLength <= size; ++i) {
        if (memcmp(methtype + i, kMarker, markerLength) != 0) continue;
        sawLayout = true;
        uint32_t bit = 0;
        bool found = false;
        const uint32_t status = bitFromLayout(methtype, size, i + markerLength,
                                              field, &bit, &found);
        if (status != Ok) return status;
        if (!found) continue;
        any = true;
        if (!agreed) { agreed = true; agreedBit = bit; }
        else if (agreedBit != bit) return LayoutConflict;
    }
    if (!sawLayout) return NoMetadata;
    if (!any) return FieldAbsent;
    if (agreedBit >= kWordBits) return FieldTooWide;
    *bitOut = agreedBit;
    return Ok;
}

/// Scan `text` for the settings-constructor shape whose immediate has `bit` set.
/// Sets `site.candidates`; a usable result requires exactly one.
inline void findSite(const uint8_t *text, size_t size, uint32_t bit, Site *site) {
    site->bit = bit;
    site->candidates = 0;
    site->status = NoCandidate;
    if (text == nullptr || bit >= kWordBits || size < 16) return;
    const uint64_t mask = uint64_t(1) << bit;
    for (size_t p = 0; p + 16 <= size; ++p) {
        // movabs r64, imm64
        if (text[p] != 0x48 && text[p] != 0x49) continue;
        if (text[p + 1] < 0xb8 || text[p + 1] > 0xbf) continue;
        const uint64_t immediate = readU64LE(text + p + 2);
        if ((immediate & mask) == 0) continue;
        // or r64, r64  (register-direct: mod == 11)
        if (!isRexW(text[p + 10]) || text[p + 11] != 0x09 ||
            (text[p + 12] & 0xc0) != 0xc0) continue;
        // mov [r64], r64  (no displacement, no SIB)
        if (!isRexW(text[p + 13]) || text[p + 14] != 0x89 ||
            (text[p + 15] & 0xc0) != 0x00 || (text[p + 15] & 0x07) == 0x04) continue;
        if (++site->candidates == 1) {
            site->instructionOffset = uint64_t(p);
            site->immediate = immediate;
            site->byteOffset = uint64_t(p) + 2 + (bit / 8);
            site->bitInByte = uint8_t(bit % 8);
            site->currentByte = text[p + 2 + (bit / 8)];
            site->patchedByte = uint8_t(site->currentByte & ~(1u << site->bitInByte));
            site->alreadyClear = false;
        }
        if (site->candidates > 1) break;   // ambiguity is fatal; stop early
    }
    site->status = site->candidates == 1 ? Ok
                 : site->candidates == 0 ? NoCandidate : Ambiguous;
}

/// Full locate: derive the bit from metadata, then find the unique constructor site.
inline Site locate(const uint8_t *methtype, size_t methtypeSize,
                   const uint8_t *text, size_t textSize, const char *field) {
    Site site {};
    uint32_t bit = 0;
    const uint32_t status = deriveBit(methtype, methtypeSize, field, &bit);
    if (status != Ok) { site.status = status; return site; }
    findSite(text, textSize, bit, &site);
    return site;
}

} // namespace RaphaelTextureSetting
