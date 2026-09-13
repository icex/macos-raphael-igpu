#include <array>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "../src/KiqQueuePreparation.hpp"

static void require(bool condition, const char *message) {
    if (!condition) {
        std::fprintf(stderr, "FAIL: %s\n", message);
        std::exit(1);
    }
}

struct FakeQueue {
    using Register = RaphaelKiq::QueueRegister;
    std::array<uint32_t, 7> value {};
    std::vector<Register> writes;
    bool retireOnDequeue {true};
    bool ignoreWptrLoClear {false};
    bool ignoreDoorbellDisable {false};
    bool reactivateAfterPointerClear {false};

    uint32_t read(Register reg) const {
        return value[static_cast<unsigned>(reg)];
    }

    void write(Register reg, uint32_t next) {
        writes.push_back(reg);
        if (reg == Register::Doorbell && ignoreDoorbellDisable) return;
        if (reg == Register::WptrLo && ignoreWptrLoClear) return;
        value[static_cast<unsigned>(reg)] = next;
        if (reg == Register::Dequeue && next == 1 && retireOnDequeue)
            value[static_cast<unsigned>(Register::Active)] = 0;
        if (reg == Register::WptrLo && reactivateAfterPointerClear)
            value[static_cast<unsigned>(Register::Active)] = 1;
    }

    unsigned pointerWrites() const {
        unsigned count = 0;
        for (auto reg : writes)
            if (reg == Register::Rptr || reg == Register::WptrHi || reg == Register::WptrLo)
                ++count;
        return count;
    }
};

struct FakeEop {
    using Register = RaphaelKiq::EopRegister;
    std::array<uint32_t, 3> value {};
    std::vector<Register> writes;
    bool ignoreWrites {false};

    uint32_t read(Register reg) const { return value[static_cast<unsigned>(reg)]; }
    void write(Register reg, uint32_t next) {
        writes.push_back(reg);
        if (!ignoreWrites) value[static_cast<unsigned>(reg)] = next;
    }
};

static RaphaelKiq::QueuePreparation prepare(FakeQueue &queue, unsigned &nativeCalls) {
    auto result = RaphaelKiq::prepareQueueForNativeStart(
        [&](RaphaelKiq::QueueRegister reg) { return queue.read(reg); },
        [&](RaphaelKiq::QueueRegister reg, uint32_t value) { queue.write(reg, value); },
        [](unsigned) {}, 100, 10);
    if (result.ready()) ++nativeCalls;
    return result;
}

int main() {
    using RaphaelKiq::QueuePreparationStatus;
    using Register = RaphaelKiq::QueueRegister;

    FakeEop eop;
    require(RaphaelKiq::programEopForNativeStart(
                [&](RaphaelKiq::EopRegister reg) { return eop.read(reg); },
                [&](RaphaelKiq::EopRegister reg, uint32_t value) { eop.write(reg, value); },
                0x8400000800ULL),
            "mode-2 EOP programming succeeds with readable registers");
    require(eop.writes == std::vector<FakeEop::Register> {
                FakeEop::Register::BaseLo, FakeEop::Register::BaseHi,
                FakeEop::Register::Control} &&
                eop.read(FakeEop::Register::BaseLo) == 0x84000008U &&
                eop.read(FakeEop::Register::BaseHi) == 0U &&
                eop.read(FakeEop::Register::Control) == 6U,
            "EOP writes use encoded base low/high and the native v10 control");
    require(std::all_of(eop.writes.begin(), eop.writes.end(), [](FakeEop::Register reg) {
                return reg == FakeEop::Register::BaseLo || reg == FakeEop::Register::BaseHi ||
                    reg == FakeEop::Register::Control;
            }),
            "mode-2 EOP programming never changes speculative doorbell bits");
    FakeEop rejected;
    rejected.ignoreWrites = true;
    require(!RaphaelKiq::programEopForNativeStart(
                 [&](RaphaelKiq::EopRegister reg) { return rejected.read(reg); },
                 [&](RaphaelKiq::EopRegister reg, uint32_t value) { rejected.write(reg, value); },
                 0x8400000800ULL),
            "EOP readback failure blocks native submission");

    FakeQueue clean;
    unsigned nativeCalls = 0;
    auto result = prepare(clean, nativeCalls);
    require(result.status == QueuePreparationStatus::Ready && nativeCalls == 1,
            "a clean inactive queue reaches native initialization");
    require(clean.pointerWrites() == 0,
            "an already-zero queue does not receive redundant pointer writes");

    FakeQueue stale;
    stale.value[static_cast<unsigned>(Register::WptrLo)] = 256;
    nativeCalls = 0;
    result = prepare(stale, nativeCalls);
    require(result.status == QueuePreparationStatus::Ready && nativeCalls == 1,
            "an inactive queue with an old producer pointer is normalized");
    require(stale.pointerWrites() == 3 && stale.read(Register::Rptr) == 0 &&
                stale.read(Register::WptrHi) == 0 && stale.read(Register::WptrLo) == 0,
            "normalization clears RPTR, WPTR_HI and WPTR_LO");
    auto pointer = stale.writes.end() - 3;
    require(pointer[0] == Register::Rptr && pointer[1] == Register::WptrHi &&
                pointer[2] == Register::WptrLo,
            "pointer reset mirrors Apple's active-branch write order");

    FakeQueue retired;
    retired.value[static_cast<unsigned>(Register::Active)] = 1;
    retired.value[static_cast<unsigned>(Register::WptrLo)] = 256;
    nativeCalls = 0;
    result = prepare(retired, nativeCalls);
    require(result.status == QueuePreparationStatus::Ready && result.elapsedUs == 10 &&
                nativeCalls == 1,
            "a genuinely retired active queue reaches native initialization");
    auto dequeueStart = retired.writes.begin() + 2;
    require(dequeueStart[0] == Register::Dequeue && dequeueStart[1] == Register::Dequeue &&
                dequeueStart[2] == Register::Rptr && dequeueStart[3] == Register::WptrHi &&
                dequeueStart[4] == Register::WptrLo,
            "dequeue completion precedes pointer normalization");
    for (auto reg : retired.writes)
        require(reg != Register::Active, "preparation never manually clears ACTIVE");

    FakeQueue ignored;
    ignored.value[static_cast<unsigned>(Register::WptrLo)] = 256;
    ignored.ignoreWptrLoClear = true;
    nativeCalls = 0;
    result = prepare(ignored, nativeCalls);
    require(result.status == QueuePreparationStatus::PointerResetFailed && nativeCalls == 0,
            "an ignored pointer write blocks native activation");

    FakeQueue lateActive;
    lateActive.value[static_cast<unsigned>(Register::WptrLo)] = 256;
    lateActive.reactivateAfterPointerClear = true;
    nativeCalls = 0;
    result = prepare(lateActive, nativeCalls);
    require(result.status == QueuePreparationStatus::QueueNotIdle && nativeCalls == 0,
            "a queue that becomes active during normalization cannot reach native activation");

    FakeQueue liveIngress;
    liveIngress.value[static_cast<unsigned>(Register::Doorbell)] = 1U << 30;
    liveIngress.ignoreDoorbellDisable = true;
    nativeCalls = 0;
    result = prepare(liveIngress, nativeCalls);
    require(result.status == QueuePreparationStatus::IngressNotDisabled &&
                liveIngress.pointerWrites() == 0 && nativeCalls == 0,
            "an ingress gate that does not close blocks normalization and native activation");

    FakeQueue timeout;
    timeout.value[static_cast<unsigned>(Register::Active)] = 1;
    timeout.retireOnDequeue = false;
    nativeCalls = 0;
    result = prepare(timeout, nativeCalls);
    require(result.status == QueuePreparationStatus::DequeueTimeout &&
                result.elapsedUs == 100 && timeout.pointerWrites() == 0 && nativeCalls == 0,
            "a genuine dequeue timeout blocks pointer writes and native activation");

    const RaphaelKiq::QueueState timeoutState {1, 1, 0x86, 0, 0xa0, 0, 0};
    require(RaphaelKiq::timeoutNativeRestoreEligible(
                true, 0x8400000000ULL, 0x8400000800ULL,
                0x8400000000ULL, 0x8400000800ULL, timeoutState, true, true, true),
            "opt-in native restore admits exact active timeout with owned identity");
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 false, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, timeoutState, true, true, true),
            "native restore flag is required");
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400001000ULL, 0x8400001800ULL,
                 0x8400000000ULL, 0x8400000800ULL, timeoutState, true, true, true),
            "native restore rejects wrong argument addresses");
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, timeoutState, false, true, true),
            "native restore rejects an invalid lease");
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, timeoutState, true, false, true),
            "native restore rejects changed owner identity");
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, timeoutState, true, true, false),
            "native restore rejects a non-native embedded MQD/EOP image");
    const RaphaelKiq::QueueState ingressState {1, 1, 0x86, 0, 0xa0, 1U << 31, 0};
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, ingressState, true, true, true),
            "native restore rejects poll ingress still enabled");
    const RaphaelKiq::QueueState doorbellState {1, 1, 0x86, 0, 0xa0, 0, 1U << 30};
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, doorbellState, true, true, true),
            "native restore rejects doorbell ingress still enabled");
    const RaphaelKiq::QueueState wrongDequeue {1, 0, 0x86, 0, 0xa0, 0, 0};
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, wrongDequeue, true, true, true),
            "native restore rejects a non-pending dequeue state");
    const RaphaelKiq::QueueState inactive {0, 1, 0x86, 0, 0xa0, 0, 0};
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, inactive, true, true, true),
            "native restore rejects an inactive timeout state");
    const RaphaelKiq::QueueState inaccessibleState {0xffffffffU, 1, 0, 0, 0, 0, 0};
    require(!RaphaelKiq::timeoutNativeRestoreEligible(
                 true, 0x8400000000ULL, 0x8400000800ULL,
                 0x8400000000ULL, 0x8400000800ULL, inaccessibleState, true, true, true),
            "native restore rejects inaccessible timeout state");

    FakeQueue inaccessible;
    inaccessible.value[static_cast<unsigned>(Register::WptrHi)] = 0xffffffffU;
    nativeCalls = 0;
    result = prepare(inaccessible, nativeCalls);
    require(result.status == QueuePreparationStatus::Inaccessible && nativeCalls == 0,
            "all-ones queue state fails closed");

    std::puts("KIQ queue preparation fixtures passed");
}
