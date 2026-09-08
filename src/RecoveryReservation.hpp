#ifndef RAPHAEL_RECOVERY_RESERVATION_HPP
#define RAPHAEL_RECOVERY_RESERVATION_HPP

#include <stdint.h>

namespace RaphaelRecovery {

constexpr uint64_t Magic = 0x3152494b55504752ULL; // "RGPUKIR1", little endian
constexpr uint32_t Version = 1;
constexpr uint32_t Pending = 0x444e4550U;          // "PEND"
constexpr uint32_t Active = 0x56544341U;           // "ACTV"
constexpr uint64_t HeapLimit = 0x0f000000ULL;
constexpr uint64_t ReservationOffset = HeapLimit;
constexpr uint64_t ScratchOffset = 0x0f100000ULL;
constexpr uint64_t ReservationEnd = 0x10000000ULL;

struct Descriptor {
    uint64_t magic;
    uint32_t version;
    uint32_t state;
    uint64_t heapLimit;
    uint64_t reservationOffset;
    uint64_t scratchOffset;
    uint64_t reservationEnd;
    uint64_t nonceLo;
    uint64_t nonceHi;
    uint64_t checksum;
};

static_assert(sizeof(Descriptor) == 72, "host and guest reservation layouts differ");

inline uint64_t checksum(const Descriptor &value) {
    return 0x9e3779b97f4a7c15ULL ^ value.magic ^ value.version ^ value.state ^
           value.heapLimit ^ value.reservationOffset ^ value.scratchOffset ^
           value.reservationEnd ^ value.nonceLo ^ value.nonceHi;
}

inline Descriptor pending(uint64_t nonceLo, uint64_t nonceHi) {
    Descriptor value {Magic, Version, Pending, HeapLimit, ReservationOffset,
                      ScratchOffset, ReservationEnd, nonceLo, nonceHi, 0};
    value.checksum = checksum(value);
    return value;
}

inline uint64_t barVisibleBytes(uint64_t pool0, uint64_t pool1) {
    const uint64_t allocatorVisible = pool0 < pool1 ? pool0 : pool1;
    // Activating the reservation caps Apple's allocators at HeapLimit, but it
    // does not shrink the PCI BAR. Diagnostics and recovery must retain access
    // to the reserved final 16 MiB while continuing to reject its end.
    return pool0 == HeapLimit && pool1 == HeapLimit
        ? ReservationEnd : allocatorVisible;
}

inline bool valid(const Descriptor &value, uint32_t state,
                  uint64_t nonceLo, uint64_t nonceHi) {
    return value.magic == Magic && value.version == Version && value.state == state &&
           value.heapLimit == HeapLimit && value.reservationOffset == ReservationOffset &&
           value.scratchOffset == ScratchOffset && value.reservationEnd == ReservationEnd &&
           value.nonceLo == nonceLo && value.nonceHi == nonceHi &&
           value.checksum == checksum(value);
}

inline bool activate(Descriptor &value, uint64_t &pool0, uint64_t &pool1) {
    if (!valid(value, Pending, value.nonceLo, value.nonceHi) ||
        pool0 < ReservationEnd || pool1 < ReservationEnd)
        return false;
    pool0 = HeapLimit;
    pool1 = HeapLimit;
    value.state = Active;
    value.checksum = checksum(value);
    return true;
}

}
#endif
