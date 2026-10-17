#pragma once
#include <stdint.h>
#include <stddef.h>

// Relocation masks ignore only link-time control-flow/RIP displacements. Native
// register choices, object offsets, immediates and instruction forms stay exact.
namespace RaphaelKernelSites {
struct Site {
    unsigned image;
    size_t reference; // Stable catalog key; never a running image address.
    const char *symbol;
    size_t symbolDelta;
    size_t targetDelta;
    const uint8_t *bytes;
    const uint8_t *mask;
    size_t length;
    bool constantData {false};
    const Site *alternatives {nullptr};
    size_t alternativeCount {0};
    const char *scopeEndSymbol {nullptr};
};
inline bool matches(const uint8_t *image, size_t size, size_t offset, const Site &site) {
    if (!image || !site.bytes || !site.mask || !site.length ||
        offset > size || site.length > size - offset) return false;
    for (size_t i = 0; i < site.length; ++i)
        if ((image[offset + i] & site.mask[i]) != (site.bytes[i] & site.mask[i])) return false;
    return true;
}
// Check a complete contract at its discovered target, including its prefix.
inline bool covers(const uint8_t *image, size_t size, size_t target,
                   const Site &site, size_t requiredSize) {
    if (target < site.targetDelta || site.targetDelta >= site.length ||
        requiredSize > site.length - site.targetDelta) return false;
    return matches(image, size, target - site.targetDelta, site);
}
// Preserve the running image's relocations. Only audited changed bytes are
// overlaid, after validating their original values; failure leaves output alone.
inline bool patchDelta(const uint8_t *live, const uint8_t *before,
                       const uint8_t *after, uint8_t *output, size_t length) {
    if (!live || !before || !after || !output || !length) return false;
    for (size_t i = 0; i < length; ++i)
        if (before[i] != after[i] && live[i] != before[i]) return false;
    for (size_t i = 0; i < length; ++i)
        output[i] = before[i] == after[i] ? live[i] : after[i];
    return true;
}
// Unique match within a validated executable/constant section. No first-match
// fallback and no UUID/version allowlist. Zero is an unambiguous failure result.
inline uintptr_t unique(const uint8_t *image, size_t size, size_t begin, size_t end,
                        const Site &site, uintptr_t base) {
    if (begin > end || end > size || site.length > end - begin) return 0;
    uintptr_t result = 0;
    for (size_t at = begin; at <= end - site.length; ++at) {
        if (!matches(image, size, at, site)) continue;
        if (result || site.targetDelta >= site.length || base > UINTPTR_MAX - at - site.targetDelta)
            return 0;
        result = base + at + site.targetDelta;
    }
    return result;
}
// A named entry remains anchored to that exact function. Interior instruction
// sites may move, but only within the symbol-bounded owner, with unique guards.
inline uintptr_t resolve(const uint8_t *image, size_t size, size_t begin, size_t end,
                         const Site &site, uintptr_t base, uintptr_t symbol,
                         uintptr_t scopeEnd = 0) {
    if (begin > end || end > size || !site.length || site.targetDelta >= site.length)
        return 0;
    if (!symbol) return unique(image, size, begin, end, site, base);
    if (symbol < base || symbol - base < begin || symbol - base >= end) return 0;
    const size_t start = symbol - base;
    if (site.scopeEndSymbol) {
        if (scopeEnd <= symbol || scopeEnd < base || scopeEnd - base > end) return 0;
        return unique(image, size, start, scopeEnd - base, site, base);
    }
    if (site.symbolDelta > end - start) return 0;
    const size_t candidate = start + site.symbolDelta;
    if (site.length > end - candidate || !matches(image, size, candidate, site) ||
        base > UINTPTR_MAX - candidate - site.targetDelta) return 0;
    return base + candidate + site.targetDelta;
}
}
