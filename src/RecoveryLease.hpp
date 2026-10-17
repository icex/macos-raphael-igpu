#ifndef RAPHAEL_RECOVERY_LEASE_HPP
#define RAPHAEL_RECOVERY_LEASE_HPP

#include <stdint.h>

// Version 2 uses a native top-down hardware reservation. The immutable OWNED
// descriptor and the one-shot POOL result are separate so a forced guest stop
// cannot leave a partially rewritten ownership record.
namespace RaphaelRecoveryV2 {

constexpr uint64_t ChecksumDomain = 0x9e3779b97f4a7c15ULL;
constexpr uint64_t OwnershipMagic = 0x3252494b55504752ULL; // "RGPUKIR2"
constexpr uint64_t PoolMagic = 0x3253504b55504752ULL;      // "RGPUKPS2"
constexpr uint32_t Version = 2;
constexpr uint32_t Owned = 0x444e574fU;                   // "OWND"
constexpr uint32_t PoolActive = 0x56544341U;              // "ACTV"
constexpr uint32_t PoolInvalid = 0x4c564e49U;             // "INVL"
constexpr uint64_t Generation = 1;
constexpr uint64_t LeaseSize = 0x15000;
constexpr uint64_t OwnershipOffset = 0;
constexpr uint64_t PoolStatusOffset = 0x100;
constexpr uint64_t ScratchRelative = 0x1000;
constexpr uint64_t ScratchEndRelative = 0x14004;

enum Reason : uint64_t {
    ReasonNone = 0,
    ReasonNativeEnable = 1,
    ReasonPoolAddress = 2,
    ReasonNativeReserve = 3,
    ReasonPoolDelta = 4,
    ReasonElement = 5,
    ReasonDuplicateEpoch = 6,
    ReasonWriteback = 7,
};

struct OwnershipDescriptor {
    uint64_t magic;
    uint32_t version;
    uint32_t state;
    uint64_t leaseOffset;
    uint64_t leaseEnd;
    uint64_t scratchOffset;
    uint64_t scratchEnd;
    uint64_t nonceLo;
    uint64_t nonceHi;
    uint64_t generation;
    uint64_t checksum;
};

struct PoolStatus {
    uint64_t magic;
    uint32_t version;
    uint32_t state;
    uint64_t leaseOffset;
    uint64_t leaseEnd;
    uint64_t nonceLo;
    uint64_t nonceHi;
    uint64_t generation;
    uint64_t pool0Before;
    uint64_t pool0After;
    uint64_t pool1Before;
    uint64_t pool1After;
    uint64_t reason;
    uint64_t checksum;
};

static_assert(sizeof(OwnershipDescriptor) == 80,
              "host and guest OWNED layouts differ");
static_assert(sizeof(PoolStatus) == 104,
              "host and guest POOL layouts differ");

inline bool checkedAdd(uint64_t a, uint64_t b, uint64_t &out) {
    if (a > UINT64_MAX - b) return false;
    out = a + b;
    return true;
}

template <typename Record, typename Write, typename Read, typename Fence>
inline bool clearRecord(Write write, Read read, Fence fence) {
    static_assert(sizeof(Record) % sizeof(uint32_t) == 0, "wire record must be dword sized");
    constexpr uint32_t count = sizeof(Record) / sizeof(uint32_t);
    for (uint32_t i = 0; i < count; ++i) write(i, 0);
    fence();
    for (uint32_t i = 0; i < count; ++i)
        if (read(i) != 0) return false;
    return true;
}

// State is the commit marker. A forced stop before its final store leaves an
// uncommitted record even if every other final byte has reached VRAM.
template <typename Record, typename Write, typename Read, typename Fence>
inline bool publishRecord(const Record &record, Write write, Read read, Fence fence) {
    static_assert(sizeof(Record) % sizeof(uint32_t) == 0, "wire record must be dword sized");
    constexpr uint32_t count = sizeof(Record) / sizeof(uint32_t);
    constexpr uint32_t stateWord = 3; // Q magic, I version, then I state.
    uint32_t words[count];
    __builtin_memcpy(words, &record, sizeof(record));
    write(stateWord, 0);
    fence();
    for (uint32_t i = 0; i < count; ++i)
        if (i != stateWord) write(i, words[i]);
    fence();
    write(stateWord, words[stateWord]);
    fence();
    for (uint32_t i = 0; i < count; ++i)
        if (read(i) != words[i]) return false;
    return true;
}

inline uint64_t checksum(const OwnershipDescriptor &v) {
    return ChecksumDomain ^ v.magic ^ static_cast<uint64_t>(v.version) ^
           static_cast<uint64_t>(v.state) ^ v.leaseOffset ^ v.leaseEnd ^
           v.scratchOffset ^ v.scratchEnd ^ v.nonceLo ^ v.nonceHi ^ v.generation;
}

inline uint64_t checksum(const PoolStatus &v) {
    return ChecksumDomain ^ v.magic ^ static_cast<uint64_t>(v.version) ^
           static_cast<uint64_t>(v.state) ^ v.leaseOffset ^ v.leaseEnd ^
           v.nonceLo ^ v.nonceHi ^ v.generation ^ v.pool0Before ^ v.pool0After ^
           v.pool1Before ^ v.pool1After ^ v.reason;
}

inline OwnershipDescriptor makeOwnership(uint64_t leaseOffset,
                                         uint64_t nonceLo, uint64_t nonceHi) {
    uint64_t leaseEnd = 0, scratchOffset = 0, scratchEnd = 0;
    checkedAdd(leaseOffset, LeaseSize, leaseEnd);
    checkedAdd(leaseOffset, ScratchRelative, scratchOffset);
    checkedAdd(leaseOffset, ScratchEndRelative, scratchEnd);
    OwnershipDescriptor v {OwnershipMagic, Version, Owned, leaseOffset, leaseEnd,
                           scratchOffset, scratchEnd, nonceLo, nonceHi, Generation, 0};
    v.checksum = checksum(v);
    return v;
}

inline bool validOwnership(const OwnershipDescriptor &v, uint64_t nonceLo,
                           uint64_t nonceHi, uint64_t visibleBytes) {
    uint64_t leaseEnd = 0, scratchOffset = 0, scratchEnd = 0;
    return v.magic == OwnershipMagic && v.version == Version && v.state == Owned &&
           v.generation == Generation && v.nonceLo == nonceLo && v.nonceHi == nonceHi &&
           v.leaseOffset != 0 && v.leaseOffset != UINT64_MAX &&
           (v.leaseOffset & 0xfffULL) == 0 &&
           checkedAdd(v.leaseOffset, LeaseSize, leaseEnd) && v.leaseEnd == leaseEnd &&
           checkedAdd(v.leaseOffset, ScratchRelative, scratchOffset) &&
           v.scratchOffset == scratchOffset &&
           checkedAdd(v.leaseOffset, ScratchEndRelative, scratchEnd) &&
           v.scratchEnd == scratchEnd && v.scratchEnd <= v.leaseEnd &&
           v.leaseEnd <= visibleBytes && v.checksum == checksum(v);
}

// The durable locator text uses the same field order as the wire record and
// host parser. Keep this adapter shared by both OWNED and POOL logging so a
// visually plausible nonce cannot silently bind the opposite 64-bit halves.
struct LogNonce { uint64_t first, second; };
inline LogNonce logNonce(const OwnershipDescriptor &v) {
    return {v.nonceLo, v.nonceHi};
}

inline PoolStatus makePoolStatus(const OwnershipDescriptor &owned, uint32_t state,
                                 uint64_t pool0Before, uint64_t pool0After,
                                 uint64_t pool1Before, uint64_t pool1After,
                                 uint64_t reason) {
    PoolStatus v {PoolMagic, Version, state, owned.leaseOffset, owned.leaseEnd,
                  owned.nonceLo, owned.nonceHi, owned.generation,
                  pool0Before, pool0After, pool1Before, pool1After, reason, 0};
    v.checksum = checksum(v);
    return v;
}

inline bool exactDecrease(uint64_t before, uint64_t after) {
    return before >= after && before - after == LeaseSize;
}

inline bool validPoolStatus(const PoolStatus &v, const OwnershipDescriptor &owned) {
    if (v.magic != PoolMagic || v.version != Version ||
        v.leaseOffset != owned.leaseOffset || v.leaseEnd != owned.leaseEnd ||
        v.nonceLo != owned.nonceLo || v.nonceHi != owned.nonceHi ||
        v.generation != owned.generation || v.checksum != checksum(v)) return false;
    if (v.state == PoolActive)
        return v.reason == ReasonNone && exactDecrease(v.pool0Before, v.pool0After) &&
               exactDecrease(v.pool1Before, v.pool1After);
    return v.state == PoolInvalid && v.reason >= ReasonNativeEnable &&
           v.reason <= ReasonWriteback;
}

inline LogNonce logNonce(const PoolStatus &v) {
    return {v.nonceLo, v.nonceHi};
}

inline bool disjointFromRange(const OwnershipDescriptor &owned,
                              uint64_t rangeOffset, uint64_t rangeBytes,
                              uint64_t visibleBytes) {
    uint64_t rangeEnd = 0;
    return validOwnership(owned, owned.nonceLo, owned.nonceHi, visibleBytes) &&
           rangeBytes != 0 && checkedAdd(rangeOffset, rangeBytes, rangeEnd) &&
           rangeEnd <= visibleBytes &&
           (owned.leaseEnd <= rangeOffset || rangeEnd <= owned.leaseOffset);
}

// The lease record is CPU-written through the BAR, while a native VMM arena may
// occupy the upper logical framebuffer outside that BAR. Keep ownership validation
// on the visible bound and apply the logical bound only to the candidate range.
inline bool logicalDisjointFromRange(const OwnershipDescriptor &owned,
                                     uint64_t rangeOffset, uint64_t rangeBytes,
                                     uint64_t logicalBytes, uint64_t visibleBytes) {
    uint64_t rangeEnd = 0;
    return validOwnership(owned, owned.nonceLo, owned.nonceHi, visibleBytes) &&
           rangeBytes != 0 && logicalBytes >= visibleBytes &&
           checkedAdd(rangeOffset, rangeBytes, rangeEnd) && rangeEnd <= logicalBytes &&
           (owned.leaseEnd <= rangeOffset || rangeEnd <= owned.leaseOffset);
}

inline bool fullPoolAddress(uint64_t memoryBase, uint64_t leaseOffset, uint64_t &out) {
    return checkedAdd(memoryBase, leaseOffset, out);
}

inline bool topDownReserve(uint64_t cursor, uint64_t size, uint32_t alignment,
                           uint64_t &offset, uint64_t &nextCursor) {
    if (alignment == 0 || (alignment & (alignment - 1)) != 0 || cursor <= size)
        return false;
    const uint64_t value = (cursor - size) & ~(static_cast<uint64_t>(alignment) - 1);
    if (value == 0) return false;
    offset = value;
    nextCursor = value;
    return true;
}

inline bool predictNativeVmmRange(uint64_t primaryCursor, uint64_t secondaryCursor,
                                  uint64_t vmmBytes, uint32_t alignment,
                                  uint64_t visibleBytes, uint64_t logicalBytes,
                                  uint64_t nativeTotal, uint64_t nativeVisible,
                                  uint64_t &offset,
                                  uint64_t &nextCursor) {
    const uint64_t cursor = nativeTotal > nativeVisible ? secondaryCursor : primaryCursor;
    if (!topDownReserve(cursor, vmmBytes, alignment, offset, nextCursor) ||
        logicalBytes == 0 || logicalBytes < visibleBytes ||
        nativeVisible > nativeTotal || nativeVisible > logicalBytes ||
        cursor > nativeTotal)
        return false;
    uint64_t end = 0;
    if (!checkedAdd(offset, vmmBytes, end) || end > logicalBytes) return false;
    if (nativeTotal > nativeVisible)
        return offset >= nativeVisible;
    return end <= nativeVisible;
}

struct NativePoolSizes { uint64_t total; uint64_t visible; };
struct DiscoveredPoolCapacities {
    uint64_t totalCapacity;
    uint64_t visibleCapacity;
    NativePoolSizes pools;
};
inline bool discoverPoolCapacities(uint32_t fbBase, uint32_t fbTop, uint64_t barBytes,
                                   uint64_t providerTotal, uint64_t providerVisible,
                                   DiscoveredPoolCapacities &out) {
    if (fbBase == 0 || fbTop < fbBase || (fbBase | fbTop) > 0x00ffffffu ||
        barBytes == 0 || providerTotal == 0 || providerVisible == 0 ||
        providerVisible > providerTotal) return false;
    const uint64_t units = static_cast<uint64_t>(fbTop - fbBase) + 1;
    if (units > UINT64_MAX / 0x1000000ULL) return false;
    const uint64_t totalCapacity = units * 0x1000000ULL;
    const uint64_t visibleCapacity = barBytes < totalCapacity ? barBytes : totalCapacity;
    if (providerTotal > totalCapacity || providerVisible > visibleCapacity) return false;
    out = {totalCapacity, visibleCapacity, {providerTotal, providerVisible}};
    return true;
}
struct ThreeArgumentPoolInit {
    uint64_t totalEnd;
    uint64_t reservedStart;
    uint64_t reservedLength;
};

inline NativePoolSizes nativePoolSizes(uint64_t total, uint64_t visible) {
    if (visible > total) visible = total;
    return {total, visible};
}

inline ThreeArgumentPoolInit threeArgumentPoolInit(uint64_t base,
                                                   NativePoolSizes sizes) {
    uint64_t totalEnd = 0, reservedStart = 0;
    checkedAdd(base, sizes.total, totalEnd);
    checkedAdd(base, sizes.visible, reservedStart);
    return {totalEnd, reservedStart, 0};
}

inline uint64_t compatibilityPoolSize(NativePoolSizes sizes) {
    return sizes.total < sizes.visible ? sizes.total : sizes.visible;
}

enum class Phase : uint32_t {
    Requested, OwnershipPublishing, Owned, PoolInitializing, PoolVerified,
    Active, Invalid
};

class LeaseState {
public:
    bool beginOwnershipPublication() {
        return transition(Phase::Requested, Phase::OwnershipPublishing);
    }

    bool finishOwnershipPublication(const OwnershipDescriptor &value) {
        if (phase() != Phase::OwnershipPublishing) return false;
        owned_ = value;
        return transition(Phase::OwnershipPublishing, Phase::Owned);
    }

    bool publishOwned(const OwnershipDescriptor &value) {
        return beginOwnershipPublication() && finishOwnershipPublication(value);
    }

    bool beginPoolInit() {
        return transition(Phase::Owned, Phase::PoolInitializing);
    }

    bool finishPoolInit(const PoolStatus &status, void *element,
                        uint64_t fullAddress, uint64_t pool0ElementStart,
                        uint64_t pool1ElementStart) {
        if (phase() != Phase::PoolInitializing) return false;
        if (element == nullptr || pool0ElementStart != fullAddress ||
            pool1ElementStart != fullAddress || status.state != PoolActive ||
            !validPoolStatus(status, owned_)) {
            invalidate();
            return false;
        }
        retainedElement_ = element;
        return transition(Phase::PoolInitializing, Phase::PoolVerified);
    }

    bool commitPoolPublication() {
        return transition(Phase::PoolVerified, Phase::Active);
    }

    void invalidate() {
        __atomic_store_n(&phase_, raw(Phase::Invalid), __ATOMIC_RELEASE);
    }
    bool canAcquire() const { return phase() == Phase::Requested; }
    bool kiqAllowed() const {
        const auto current = phase();
        return current == Phase::Owned || current == Phase::PoolInitializing ||
               current == Phase::Active;
    }
    bool clientsAllowed() const { return phase() == Phase::Active; }
    Phase phase() const {
        return static_cast<Phase>(
            __atomic_load_n(&phase_, __ATOMIC_ACQUIRE));
    }
    const OwnershipDescriptor &ownership() const { return owned_; }
    void *retainedElement() const { return retainedElement_; }

private:
    static constexpr uint32_t raw(Phase phase) {
        return static_cast<uint32_t>(phase);
    }
    bool transition(Phase from, Phase to) {
        uint32_t expected = raw(from);
        return __atomic_compare_exchange_n(
            &phase_, &expected, raw(to), false,
            __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }

    uint32_t phase_ {raw(Phase::Requested)};
    OwnershipDescriptor owned_ {};
    void *retainedElement_ {nullptr};
};

struct PoolFreeSnapshot {
    bool valid;
    uint64_t pool0;
    uint64_t pool1;
};

struct NativeReserveEvidence {
    bool returned;
    void *element;
    uint64_t pool0Start;
    uint64_t pool1Start;
};

struct PoolActivationResult {
    uint32_t nativeResult;
    bool active;
    uint64_t fullAddress;
    uint64_t reason;
    PoolFreeSnapshot before;
    PoolFreeSnapshot after;
    NativeReserveEvidence reserve;
};

// The routed enable callback uses this exact sequence: one native pool init,
// snapshot both allocators, reserve the full software-domain lease address,
// snapshot both again, then publish a terminal status before admitting clients.
template <typename NativeEnable, typename ReadFree, typename Reserve,
          typename Publish, typename AuthorizeClients>
inline PoolActivationResult establishPools(
    LeaseState &state, uint64_t memoryBase, NativeEnable nativeEnable,
    ReadFree readFree, Reserve reserve, Publish publish,
    AuthorizeClients authorizeClients) {
    PoolActivationResult result {};
    if (!state.beginPoolInit()) {
        result.reason = ReasonDuplicateEpoch;
        state.invalidate();
        return result;
    }
    // X6000's native Boolean return is carried in AL. Some implementations
    // leave the upper EAX bits untouched, so never interpret the whole register
    // as a truth value when the callback is modeled with an integer return.
    result.nativeResult =
        (static_cast<uint32_t>(nativeEnable()) & 0xffU) == 1U ? 1U : 0U;
    result.before = readFree();
    if (!result.nativeResult) {
        result.reason = ReasonNativeEnable;
    } else if (!result.before.valid ||
               !fullPoolAddress(memoryBase, state.ownership().leaseOffset,
                                result.fullAddress)) {
        result.reason = ReasonPoolAddress;
    } else {
        result.reserve = reserve(result.fullAddress, LeaseSize);
        result.after = readFree();
        if (!result.reserve.returned) result.reason = ReasonNativeReserve;
        else if (result.reserve.element == nullptr ||
                 result.reserve.pool0Start != result.fullAddress ||
                 result.reserve.pool1Start != result.fullAddress)
            result.reason = ReasonElement;
        else if (!result.after.valid ||
                 !exactDecrease(result.before.pool0, result.after.pool0) ||
                 !exactDecrease(result.before.pool1, result.after.pool1))
            result.reason = ReasonPoolDelta;
    }
    if (result.reason == ReasonNone) {
        auto status = makePoolStatus(state.ownership(), PoolActive,
            result.before.pool0, result.after.pool0,
            result.before.pool1, result.after.pool1, ReasonNone);
        if (state.finishPoolInit(status, result.reserve.element, result.fullAddress,
                                result.reserve.pool0Start, result.reserve.pool1Start) &&
            publish(status) && authorizeClients(status) &&
            state.commitPoolPublication()) {
            result.active = true;
            return result;
        }
        result.reason = ReasonWriteback;
    }
    auto invalid = makePoolStatus(state.ownership(), PoolInvalid,
        result.before.pool0, result.after.pool0,
        result.before.pool1, result.after.pool1, result.reason);
    publish(invalid);
    state.invalidate();
    return result;
}

// This is also used by the routed VMM callback, so tests exercise the actual
// append -> immutable publication -> native VMM ordering boundary.
template <typename Preflight, typename Append, typename Validate,
          typename Publish, typename NativeVmm>
inline bool establishBeforeVmm(LeaseState &state, uint64_t nonceLo,
                               uint64_t nonceHi, uint64_t visibleBytes,
                               Preflight preflight, Append append, Validate validate,
                               Publish publish, NativeVmm nativeVmm) {
    if (!state.beginOwnershipPublication()) {
        state.invalidate();
        return false;
    }
    if (!preflight()) {
        state.invalidate();
        return false;
    }
    const uint64_t leaseOffset = append();
    const auto owned = makeOwnership(leaseOffset, nonceLo, nonceHi);
    const bool accepted = validOwnership(owned, nonceLo, nonceHi, visibleBytes) &&
                          validate(owned) && publish(owned) &&
                          state.finishOwnershipPublication(owned);
    if (!accepted) state.invalidate();
    if (accepted) nativeVmm();
    return accepted;
}

} // namespace RaphaelRecoveryV2

#endif
