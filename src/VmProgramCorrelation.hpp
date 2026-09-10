#pragma once

#include <stddef.h>
#include <stdint.h>

#include "GpuVmDiagnostics.hpp"
#include "SdmaAddresses.hpp"

namespace RaphaelVm {

enum class CorrelationReason : uint32_t {
    Matched,
    InvalidSubmit,
    NoProgram,
    NoSameThread,
    NoEarlier,
    NoInRange,
};

static constexpr size_t kNoProgramMatch = static_cast<size_t>(-1);

struct ProgramCorrelation {
    size_t matchedIndex;
    CorrelationReason reason;
    size_t retained;
    size_t sameThread;
    size_t earlier;
    size_t inRange;
};

inline bool validProgramForSubmit(const PreparedRequest &program) {
    return program.valid && program.request.valid && program.request.hub == 0 &&
        program.request.vmid == 2 && program.request.reprogram;
}

inline bool validSubmitForCorrelation(
        const RaphaelSdma::SubmitInfoObservation &submit) {
    if (!submit.layoutValid || submit.vmid != 2 || submit.entries == 0 ||
        submit.entries > 4)
        return false;
    for (uint32_t n = 0; n < submit.entries; ++n)
        if (submit.addresses[n] != 0) return true;
    return false;
}

inline bool submitInsideProgram(
        const RaphaelSdma::SubmitInfoObservation &submit,
        const PreparedRequest &program) {
    if (!validSubmitForCorrelation(submit) || !validProgramForSubmit(program))
        return false;
    for (uint32_t n = 0; n < submit.entries; ++n) {
        const uint64_t address = submit.addresses[n];
        if (address != 0 &&
            (address < program.request.start || address > program.request.end))
            return false;
    }
    return true;
}

template <typename Programs>
inline ProgramCorrelation correlateSubmit(
        const RaphaelSdma::SubmitInfoObservation &submit,
        const Programs *programs, size_t count) {
    ProgramCorrelation result {kNoProgramMatch, CorrelationReason::InvalidSubmit,
                               count, 0, 0, 0};
    if (!validSubmitForCorrelation(submit)) return result;
    if (programs == nullptr || count == 0) {
        result.reason = CorrelationReason::NoProgram;
        return result;
    }

    for (size_t n = 0; n < count; ++n) {
        const auto &candidate = programs[n];
        if (!validProgramForSubmit(candidate) ||
            candidate.threadToken != submit.threadToken)
            continue;
        ++result.sameThread;
        if (candidate.sequence >= submit.eventOrder) continue;
        ++result.earlier;
        if (!submitInsideProgram(submit, candidate)) continue;
        ++result.inRange;
    }

    // Prefer the exact sequence captured by the producer callback, but require
    // every independently observed predicate. A newer prepare can race the hint
    // publication, so fall back to the newest retained qualifying predecessor.
    for (size_t n = count; n > 0; --n) {
        const auto &candidate = programs[n - 1];
        if (candidate.sequence == submit.vmProgramSequence &&
            candidate.threadToken == submit.threadToken &&
            candidate.sequence < submit.eventOrder &&
            submitInsideProgram(submit, candidate)) {
            result.matchedIndex = n - 1;
            result.reason = CorrelationReason::Matched;
            return result;
        }
    }
    for (size_t n = count; n > 0; --n) {
        const auto &candidate = programs[n - 1];
        if (candidate.threadToken == submit.threadToken &&
            candidate.sequence < submit.eventOrder &&
            submitInsideProgram(submit, candidate)) {
            result.matchedIndex = n - 1;
            result.reason = CorrelationReason::Matched;
            return result;
        }
    }

    result.reason = result.sameThread == 0 ? CorrelationReason::NoSameThread
        : result.earlier == 0 ? CorrelationReason::NoEarlier
        : CorrelationReason::NoInRange;
    return result;
}

inline const char *correlationReasonName(CorrelationReason reason) {
    switch (reason) {
        case CorrelationReason::Matched: return "matched";
        case CorrelationReason::InvalidSubmit: return "invalid-submit";
        case CorrelationReason::NoProgram: return "no-program";
        case CorrelationReason::NoSameThread: return "no-same-thread";
        case CorrelationReason::NoEarlier: return "no-earlier";
        case CorrelationReason::NoInRange: return "no-in-range";
    }
    return "invalid-submit";
}

} // namespace RaphaelVm
