#pragma once

#include <stddef.h>
#include <stdint.h>

namespace rgpu {

class CriticalWorkerBudget {
    uint64_t started_;
    uint64_t duration_;
public:
    CriticalWorkerBudget(uint64_t started, uint64_t duration) :
        started_(started), duration_(duration) {}

    uint64_t remainingUs(uint64_t now) const {
        const uint64_t elapsed = now - started_;
        return elapsed >= duration_ ? 0 : duration_ - elapsed;
    }
    uint64_t cappedOperationUs(uint64_t now, uint64_t requested) const {
        const uint64_t remaining = remainingUs(now);
        return requested < remaining ? requested : remaining;
    }
    unsigned cappedSleepMs(uint64_t now, unsigned requested) const {
        const uint64_t availableMs = remainingUs(now) / 1000;
        return requested < availableMs ? requested : static_cast<unsigned>(availableMs);
    }
};

template <typename Io>
class CriticalUart {
    static constexpr uint16_t kData = 0;
    static constexpr uint16_t kIer = 1;
    static constexpr uint16_t kFcr = 2;
    static constexpr uint16_t kLcr = 3;
    static constexpr uint16_t kMcr = 4;
    static constexpr uint16_t kLsr = 5;
    static constexpr uint8_t kThre = 0x20;

    Io &io_;
    bool initialized_ {};
    bool failed_ {};
    uint64_t snapshotStarted_ {};
    uint64_t snapshotTimeoutUs_ {kSnapshotTimeoutUs};

    bool put(uint8_t byte) {
        if (!initialized_ || failed_) return false;
        const uint64_t byteStarted = io_.micros();
        while ((io_.read(kBase + kLsr) & kThre) == 0) {
            const uint64_t now = io_.micros();
            if (now - byteStarted >= kByteTimeoutUs ||
                now - snapshotStarted_ >= snapshotTimeoutUs_) {
                failed_ = true;
                return false;
            }
            io_.delay(kPollIntervalUs);
        }
        if (io_.micros() - snapshotStarted_ >= snapshotTimeoutUs_) {
            failed_ = true;
            return false;
        }
        io_.write(kBase + kData, byte);
        return true;
    }

    bool writeText(const char *text) {
        if (!initialized_ || failed_ || text == nullptr) return false;
        for (size_t i = 0; text[i] != '\0'; ++i)
            if (!put(static_cast<uint8_t>(text[i]))) return false;
        return put('\r') && put('\n');
    }

    bool writeFragment(const char *text) {
        if (!initialized_ || failed_ || text == nullptr) return false;
        for (size_t i = 0; text[i] != '\0'; ++i)
            if (!put(static_cast<uint8_t>(text[i]))) return false;
        return true;
    }

public:
    static constexpr uint16_t kBase = 0x2f8;
    static constexpr unsigned kIndex = 1;
    static constexpr unsigned kPortNumber = 2;
    static constexpr uint64_t kPollIntervalUs = 10;
    static constexpr uint64_t kByteTimeoutUs = 2000;
    static constexpr uint64_t kSnapshotTimeoutUs = UINT64_C(110000000);
    static constexpr size_t kMaximumSnapshotWireBytes =
        2u + 512u * 13u * (172u + 2u) + 206u + 2u;

    explicit CriticalUart(Io &io) : io_(io) {}

    bool initialize() {
        initialized_ = false;
        failed_ = false;
        if (io_.read(kBase + kLsr) == 0xff) {
            failed_ = true;
            return false;
        }
        io_.write(kBase + kLcr, 0x03); // Clear unknown DLAB state before addressing IER.
        io_.write(kBase + kIer, 0x00); // UART interrupts off; CPU interrupt state untouched.
        io_.write(kBase + kLcr, 0x80); // DLAB.
        io_.write(kBase + kData, 0x01); // 115200 baud divisor, low byte.
        io_.write(kBase + kIer, 0x00);  // Divisor high byte while DLAB is set.
        io_.write(kBase + kLcr, 0x03); // 8 data bits, no parity, one stop bit.
        io_.write(kBase + kFcr, 0x07); // Enable and clear both FIFOs.
        io_.write(kBase + kMcr, 0x03); // DTR and RTS.
        initialized_ = io_.read(kBase + kLcr) == 0x03 &&
                       io_.read(kBase + kLsr) != 0xff;
        failed_ = !initialized_;
        return initialized_;
    }

    void beginSnapshot(uint64_t timeoutUs = kSnapshotTimeoutUs) {
        failed_ = !initialized_;
        snapshotStarted_ = io_.micros();
        snapshotTimeoutUs_ = timeoutUs;
        // A previous attempt can stop halfway through a physical line. Bound and
        // delimit that fragment before the next canonical header is emitted.
        if (!failed_) put('\r') && put('\n');
    }

    bool writeReady(const char *build, uint64_t timeoutUs = kByteTimeoutUs * 80) {
        if (build == nullptr) return false;
        for (size_t i = 0; i < 32; ++i) {
            const char ch = build[i];
            if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f')))
                return false;
        }
        if (build[32] != '\0') return false;
        beginSnapshot(timeoutUs);
        static constexpr char prefix[] = "RGPU_UART_READY v=1 b=";
        static constexpr char suffix[] = " port=2";
        if (!writeFragment(prefix)) return false;
        // The build identity is validated by the unchanged CR2 formatter; enforce its
        // fixed field width here so readiness can never consume an unbounded string.
        for (size_t i = 0; i < 32; ++i) {
            if (!put(build[i])) return false;
        }
        return writeText(suffix);
    }

    void operator()(const char *line) { writeText(line); }
    bool failed() const { return failed_; }
};

} // namespace rgpu
