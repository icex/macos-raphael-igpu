// Structural locator for AMD_DeviceSettings flags.
//
// The point of this locator is to survive a macOS update that moves code, renumbers
// unrelated flags, or changes the default mask -- while refusing, rather than guessing,
// when the constructor shape itself changes. These tests encode exactly that contract.
//
//   g++ -std=c++14 -Wall -Wextra -Werror -fsanitize=undefined
//       tests/test_texture_setting_locator.cpp -o /tmp/locator-test && /tmp/locator-test
//
// If RGPU_MTL_TEXT is set to a raw __TEXT dump of a real AMDRadeonX6000MTLDriver, the
// last check also validates against that image.

#include "../src/TextureSettingLocator.hpp"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

using namespace RaphaelTextureSetting;

static int failures = 0;

static void check(bool condition, const char *what) {
    if (!condition) { std::printf("FAIL: %s\n", what); ++failures; }
}

static void checkEqual(uint64_t actual, uint64_t expected, const char *what) {
    if (actual != expected) {
        std::printf("FAIL: %s (got %llu, want %llu)\n", what,
                    (unsigned long long)actual, (unsigned long long)expected);
        ++failures;
    }
}

// ---------------------------------------------------------------- fixtures

// A metadata run naming `count` boolean flags, with `target` at index `at`.
static std::string layout(const char *target, unsigned at, unsigned count) {
    std::string out = "{AMD_DeviceSettings=";
    for (unsigned i = 0; i < count; ++i) {
        out += '"';
        out += (i == at) ? target : ("flag" + std::to_string(i));
        out += "\"b1";
    }
    out += "}";
    return out;
}

// movabs r64,imm64 ; or r64,r64 ; mov [r64],r64 -- the settings-constructor shape.
static void emitSite(std::vector<uint8_t> &code, uint64_t immediate) {
    code.push_back(0x48); code.push_back(0xb8);
    for (int i = 0; i < 8; ++i) code.push_back(uint8_t((immediate >> (8 * i)) & 0xff));
    code.push_back(0x48); code.push_back(0x09); code.push_back(0xf0);
    code.push_back(0x48); code.push_back(0x89); code.push_back(0x07);
}

static void emitFiller(std::vector<uint8_t> &code, size_t bytes) {
    for (size_t i = 0; i < bytes; ++i) code.push_back(0x90);
}

// ---------------------------------------------------------------- checks

static void testDerivesBitFromMetadata() {
    const std::string meta = layout("enableTexturePipeBankXor", 27, 74);
    uint32_t bit = 0;
    checkEqual(deriveBit((const uint8_t *)meta.data(), meta.size(),
                         "enableTexturePipeBankXor", &bit), Ok, "metadata parses");
    checkEqual(bit, 27, "bit index derived from metadata");
}

static void testToleratesRenumbering() {
    // An update inserts flags ahead of the target: the index must follow the metadata,
    // not a hard-coded 27.
    const std::string meta = layout("enableTexturePipeBankXor", 31, 74);
    uint32_t bit = 0;
    checkEqual(deriveBit((const uint8_t *)meta.data(), meta.size(),
                         "enableTexturePipeBankXor", &bit), Ok, "renumbered layout parses");
    checkEqual(bit, 31, "renumbered bit index follows metadata");
}

static void testRejectsBadMetadata() {
    uint32_t bit = 0;
    const std::string absent = layout("someOtherFlag", 3, 10);
    checkEqual(deriveBit((const uint8_t *)absent.data(), absent.size(),
                         "enableTexturePipeBankXor", &bit), FieldAbsent, "absent field refused");

    checkEqual(deriveBit(nullptr, 0, "enableTexturePipeBankXor", &bit), NoMetadata,
               "missing metadata refused");

    const char junk[] = "no settings encoding here at all";
    checkEqual(deriveBit((const uint8_t *)junk, sizeof(junk) - 1,
                         "enableTexturePipeBankXor", &bit), NoMetadata, "junk refused");

    // Present but not a single bit -> we must not patch a multi-bit field.
    std::string wide = "{AMD_DeviceSettings=\"a\"b1\"enableTexturePipeBankXor\"b10}";
    checkEqual(deriveBit((const uint8_t *)wide.data(), wide.size(),
                         "enableTexturePipeBankXor", &bit), FieldNotBoolean,
               "non-boolean field refused");

    // Beyond the first 64-bit word: one movabs cannot reach it.
    const std::string far = layout("enableTexturePipeBankXor", 70, 80);
    checkEqual(deriveBit((const uint8_t *)far.data(), far.size(),
                         "enableTexturePipeBankXor", &bit), FieldTooWide,
               "out-of-word field refused");

    // Two runs disagreeing on the index means we cannot trust either.
    const std::string conflict = layout("enableTexturePipeBankXor", 27, 40) +
                                 layout("enableTexturePipeBankXor", 28, 40);
    checkEqual(deriveBit((const uint8_t *)conflict.data(), conflict.size(),
                         "enableTexturePipeBankXor", &bit), LayoutConflict,
               "conflicting layouts refused");
}

static void testFindsUniqueSite() {
    std::vector<uint8_t> code;
    emitFiller(code, 64);
    const size_t at = code.size();
    emitSite(code, 0x1ff700000ull);          // bit 27 set, as in the real image
    emitFiller(code, 64);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, Ok, "unique site located");
    checkEqual(site.candidates, 1, "exactly one candidate");
    checkEqual(site.instructionOffset, at, "instruction offset");
    checkEqual(site.byteOffset, at + 2 + 3, "byte carrying bit 27");
    checkEqual(site.bitInByte, 3, "bit position within byte");
    checkEqual(site.currentByte, 0xff, "current byte");
    checkEqual(site.patchedByte, 0xf7, "patched byte clears only bit 27");
    checkEqual(site.immediate, 0x1ff700000ull, "immediate recovered");
}

static void testToleratesMovedCodeAndChangedDefaults() {
    // Same shape at a different address with a different default mask: still found.
    std::vector<uint8_t> code;
    emitFiller(code, 4096);
    const size_t at = code.size();
    emitSite(code, 0x1fb700000ull);          // an unrelated default flipped
    emitFiller(code, 128);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, Ok, "moved code still located");
    checkEqual(site.instructionOffset, at, "offset follows the code");
    checkEqual(site.currentByte, 0xfb, "unrelated default preserved");
    checkEqual(site.patchedByte, 0xf3, "only the target bit is cleared");
}

static void testIgnoresImmediatesWithoutTheBit() {
    // An AND-mask constructor elsewhere must not be mistaken for the site.
    std::vector<uint8_t> code;
    emitFiller(code, 32);
    emitSite(code, 0xfffffffff7ffffffull);   // bit 27 clear -> not a candidate
    emitFiller(code, 32);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, NoCandidate, "immediate without the bit is ignored");
    checkEqual(site.candidates, 0, "no candidates");
}

static void testRefusesAmbiguity() {
    std::vector<uint8_t> code;
    emitFiller(code, 16);
    emitSite(code, 0x1ff700000ull);
    emitFiller(code, 16);
    emitSite(code, 0x08000000ull);           // a second shape with bit 27 set
    emitFiller(code, 16);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, Ambiguous, "two candidates refused");
    check(site.candidates > 1, "ambiguity counted");
}

static void testRefusesChangedShape() {
    // movabs followed by something that is not `or r64,r64; mov [r64],r64`.
    std::vector<uint8_t> code;
    emitFiller(code, 16);
    code.push_back(0x48); code.push_back(0xb8);
    for (int i = 0; i < 8; ++i) code.push_back(uint8_t((0x1ff700000ull >> (8 * i)) & 0xff));
    for (int i = 0; i < 6; ++i) code.push_back(0x90);
    emitFiller(code, 16);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, NoCandidate, "changed constructor shape refused, not guessed");
}

static void testAlreadyClearIsRepresentable() {
    // If a future image ships the flag already disabled, the immediate no longer has the
    // bit, so there is nothing to patch and nothing to find. That is a safe no-op.
    std::vector<uint8_t> code;
    emitFiller(code, 16);
    emitSite(code, 0x1f7700000ull);
    emitFiller(code, 16);

    Site site {};
    findSite(code.data(), code.size(), 27, &site);
    checkEqual(site.status, NoCandidate, "already-disabled image needs no patch");
}

static void testEndToEndLocate() {
    const std::string meta = layout("enableTexturePipeBankXor", 27, 74);
    std::vector<uint8_t> code;
    emitFiller(code, 100);
    emitSite(code, 0x1ff700000ull);
    emitFiller(code, 100);

    const Site site = locate((const uint8_t *)meta.data(), meta.size(),
                             code.data(), code.size(), "enableTexturePipeBankXor");
    checkEqual(site.status, Ok, "end-to-end locate");
    checkEqual(site.bit, 27, "end-to-end bit");
    checkEqual(site.patchedByte, 0xf7, "end-to-end patched byte");
}

static void testRealImageWhenAvailable() {
    const char *path = std::getenv("RGPU_MTL_TEXT");
    if (path == nullptr) {
        std::printf("skip: RGPU_MTL_TEXT not set (synthetic checks only)\n");
        return;
    }
    std::FILE *file = std::fopen(path, "rb");
    if (file == nullptr) { std::printf("skip: cannot open %s\n", path); return; }
    std::fseek(file, 0, SEEK_END);
    const long size = std::ftell(file);
    std::fseek(file, 0, SEEK_SET);
    std::vector<uint8_t> blob(size > 0 ? size_t(size) : 0);
    const size_t got = blob.empty() ? 0 : std::fread(blob.data(), 1, blob.size(), file);
    std::fclose(file);
    check(got == blob.size(), "real image read");
    if (got != blob.size()) return;

    // The dump is one __TEXT segment, so metadata and code share the buffer.
    uint32_t bit = 0;
    checkEqual(deriveBit(blob.data(), blob.size(), "enableTexturePipeBankXor", &bit), Ok,
               "real image: metadata parses");
    checkEqual(bit, 27, "real image: bit 27 derived");

    Site site {};
    findSite(blob.data(), blob.size(), bit, &site);
    checkEqual(site.status, Ok, "real image: unique site");
    checkEqual(site.instructionOffset, 0x13a7e1ull, "real image: known patch site");
    checkEqual(site.immediate, 0x1ff700000ull, "real image: known immediate");
    checkEqual(site.currentByte, 0xff, "real image: current byte");
    checkEqual(site.patchedByte, 0xf7, "real image: patched byte");
    std::printf("real image: located 0x%llx uniquely\n",
                (unsigned long long)site.instructionOffset);
}

int main() {
    testDerivesBitFromMetadata();
    testToleratesRenumbering();
    testRejectsBadMetadata();
    testFindsUniqueSite();
    testToleratesMovedCodeAndChangedDefaults();
    testIgnoresImmediatesWithoutTheBit();
    testRefusesAmbiguity();
    testRefusesChangedShape();
    testAlreadyClearIsRepresentable();
    testEndToEndLocate();
    testRealImageWhenAvailable();

    if (failures != 0) { std::printf("%d check(s) failed\n", failures); return 1; }
    std::printf("all texture-setting locator checks passed\n");
    return 0;
}
