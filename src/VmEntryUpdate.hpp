#pragma once

#include <stddef.h>
#include <stdint.h>

namespace RaphaelVm {

enum class UpdateDomain : uint32_t {
    Inactive = 0,
    Converted,
    AlreadyPhysical,
    Outside,
    System,
    InvalidTemplate,
    InvalidAperture,
    Empty,
    Overflow,
    SpanOutside,
    ZeroSource,
};

static constexpr size_t kUpdateDomainCount = 11;

// CRLOG/SYSLOG concatenates its format at preprocessing time. Sharing this
// literal with the integration fixture prevents producer/parser schema drift.
#define RGPU_VM_ENTRY_UPDATE_SUMMARY_FORMAT \
    "VM: entry-update mode=%u route=%u inactive=%llu converted=%llu physical=%llu " \
    "outside=%llu system=%llu invalid-template=%llu invalid-aperture=%llu " \
    "empty=%llu overflow=%llu span=%llu zero=%llu omitted-child=%llu " \
    "omitted-eligible=%llu omitted-control=%llu"

enum class UpdateProducer : uint32_t { Leaf, Child, Unmap, Other };

struct EntryUpdateDecision {
    uint64_t destination;
    uint64_t count;
    uint64_t source;
    uint64_t result;
    uint64_t templateValue;
    uint64_t increment;
    uint64_t spanEnd;
    uint64_t constructed;
    uint64_t callerOffset;
    UpdateDomain domain;
    UpdateProducer producer;
};

constexpr UpdateProducer updateProducer(uint64_t callerOffset) {
    return callerOffset == 0x559dc ? UpdateProducer::Leaf
        : callerOffset == 0x55a72 ? UpdateProducer::Child
        : callerOffset == 0x561f6 ? UpdateProducer::Unmap
        : UpdateProducer::Other;
}

inline EntryUpdateDecision prepareEntryUpdate(
        bool active, uint32_t rawFbBase, uint32_t rawFbTop,
        uint32_t rawFbOffset, uint64_t callerOffset, uint64_t destination,
        uint64_t count, uint64_t source, uint64_t templateValue,
        uint64_t increment) {
    EntryUpdateDecision result {destination, count, source, source, templateValue,
        increment, source, templateValue | source, callerOffset,
        UpdateDomain::Inactive, updateProducer(callerOffset)};
    if (!active) return result;
    if (count == 0) {
        result.domain = UpdateDomain::Empty;
        return result;
    }
    // Bit 0 is VALID. Native clear/unmap requests use a zero template and must
    // never acquire an address merely because their source overlaps the aperture.
    if ((templateValue & 1u) == 0) {
        result.domain = UpdateDomain::InvalidTemplate;
        return result;
    }
    // At this call boundary bit 1 of the encoded template is SYSTEM. Such
    // addresses are guest physical and do not use the framebuffer aperture.
    if ((templateValue & 2u) != 0) {
        result.domain = UpdateDomain::System;
        return result;
    }
    if (rawFbBase == 0 || rawFbOffset == 0 || rawFbTop < rawFbBase ||
        ((rawFbBase | rawFbTop | rawFbOffset) & 0xff000000u)) {
        result.domain = UpdateDomain::InvalidAperture;
        return result;
    }
    if (source == 0) {
        result.domain = UpdateDomain::ZeroSource;
        return result;
    }
    const uint64_t steps = count - 1;
    if (increment != 0 && steps > UINT64_MAX / increment) {
        result.domain = UpdateDomain::Overflow;
        return result;
    }
    const uint64_t span = steps * increment;
    if (source > UINT64_MAX - span) {
        result.domain = UpdateDomain::Overflow;
        return result;
    }
    result.spanEnd = source + span;

    const uint64_t mcBase = static_cast<uint64_t>(rawFbBase) << 24;
    const uint64_t mcTop = (static_cast<uint64_t>(rawFbTop) << 24) | 0xffffffULL;
    const uint64_t physicalBase = static_cast<uint64_t>(rawFbOffset) << 24;
    const uint64_t apertureBytes = mcTop - mcBase;
    if (physicalBase > 0x0000ffffffffffffULL - apertureBytes) {
        result.domain = UpdateDomain::InvalidAperture;
        return result;
    }
    const uint64_t physicalTop = physicalBase + apertureBytes;
    if (source >= physicalBase && source <= physicalTop) {
        result.domain = result.spanEnd <= physicalTop
            ? UpdateDomain::AlreadyPhysical : UpdateDomain::SpanOutside;
        return result;
    }
    if (source < mcBase || source > mcTop) {
        result.domain = UpdateDomain::Outside;
        return result;
    }
    if (result.spanEnd > mcTop) {
        result.domain = UpdateDomain::SpanOutside;
        return result;
    }
    const uint64_t offset = source - mcBase;
    result.result = physicalBase + offset;
    result.constructed = templateValue | result.result;
    result.domain = UpdateDomain::Converted;
    return result;
}

template <typename Native>
inline void forwardEntryUpdate(Native native, void *self,
                               const EntryUpdateDecision &decision) {
    native(self, decision.destination, decision.count, decision.result,
           decision.templateValue, decision.increment);
}

inline const char *updateDomainName(UpdateDomain domain) {
    switch (domain) {
        case UpdateDomain::Inactive: return "inactive";
        case UpdateDomain::Converted: return "converted";
        case UpdateDomain::AlreadyPhysical: return "physical";
        case UpdateDomain::Outside: return "outside";
        case UpdateDomain::System: return "system";
        case UpdateDomain::InvalidTemplate: return "invalid-template";
        case UpdateDomain::InvalidAperture: return "invalid-aperture";
        case UpdateDomain::Empty: return "empty";
        case UpdateDomain::Overflow: return "overflow";
        case UpdateDomain::SpanOutside: return "span";
        case UpdateDomain::ZeroSource: return "zero";
    }
    return "unknown";
}

inline const char *updateProducerName(UpdateProducer producer) {
    switch (producer) {
        case UpdateProducer::Leaf: return "leaf";
        case UpdateProducer::Child: return "child";
        case UpdateProducer::Unmap: return "unmap";
        case UpdateProducer::Other: return "other";
    }
    return "other";
}

// Worker-side publication policy. It never waits for the callback stream to go
// quiet: exponential total thresholds bound ordinary summaries, while the first
// conversion or safety-relevant refusal is always published immediately.
class UpdateSummarySchedule {
    uint64_t nextThreshold_ {1};
    uint32_t reportedSignals_ {0};
public:
    bool shouldPublish(const uint64_t (&counts)[kUpdateDomainCount]) {
        uint64_t total = 0;
        for (size_t n = 0; n < kUpdateDomainCount; ++n)
            total = counts[n] > UINT64_MAX - total ? UINT64_MAX : total + counts[n];

        uint32_t signals = 0;
        const UpdateDomain observed[] = {
            UpdateDomain::Converted, UpdateDomain::Inactive,
            UpdateDomain::InvalidAperture, UpdateDomain::Overflow,
            UpdateDomain::SpanOutside};
        for (auto domain : observed)
            if (counts[static_cast<size_t>(domain)] != 0)
                signals |= 1u << static_cast<uint32_t>(domain);
        const bool newSignal = (signals & ~reportedSignals_) != 0;
        reportedSignals_ |= signals;

        bool threshold = nextThreshold_ != 0 && total >= nextThreshold_;
        if (threshold) {
            do {
                if (nextThreshold_ > UINT64_MAX / 2) {
                    nextThreshold_ = 0;
                    break;
                }
                nextThreshold_ *= 2;
            } while (nextThreshold_ <= total);
        }
        return threshold || newSignal;
    }
};

} // namespace RaphaelVm
