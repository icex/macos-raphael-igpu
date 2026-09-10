#include "../src/CriticalReplay.hpp"
#include "../src/CriticalUart.hpp"

#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

namespace CR = rgpu::CriticalReplayV2;

struct FakeIo {
    uint64_t now {};
    uint64_t stallAt {UINT64_MAX};
    bool absent {};
    uint64_t wireUsPerByte {};
    uint8_t lcr {};
    std::vector<std::pair<uint16_t, uint8_t>> writes;
    std::string bytes;

    uint8_t read(uint16_t port) {
        if (absent) return 0xff;
        if (port == 0x2fd) return now < stallAt ? 0x60 : 0x40;
        if (port == 0x2fb) return lcr;
        return 0;
    }
    void write(uint16_t port, uint8_t value) {
        writes.emplace_back(port, value);
        if (port == 0x2fb) lcr = value;
        if (port == 0x2f8 && (lcr & 0x80) == 0) {
            bytes.push_back(static_cast<char>(value));
            now += wireUsPerByte;
        }
    }
    uint64_t micros() const { return now; }
    void delay(unsigned us) { now += us; }
};

using Uart = rgpu::CriticalUart<FakeIo>;

static void testWorkerBudgetCapsDelayAndReadiness() {
    rgpu::CriticalWorkerBudget budget(100, 180000000);
    assert(budget.remainingUs(100) == 180000000);
    assert(budget.cappedSleepMs(100, 300000) == 180000);
    assert(budget.remainingUs(179999100) == 1000);
    assert(budget.cappedOperationUs(179999100, 160000) == 1000);
    assert(budget.cappedSleepMs(180000100, 10000) == 0);
    assert(budget.cappedOperationUs(180000100, 160000) == 0);
}

static void testInitializationOrderAndReadiness() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    const std::vector<std::pair<uint16_t, uint8_t>> expected {
        {0x2fb, 0x03}, {0x2f9, 0x00}, {0x2fb, 0x80}, {0x2f8, 0x01}, {0x2f9, 0x00},
        {0x2fb, 0x03}, {0x2fa, 0x07}, {0x2fc, 0x03},
    };
    assert(io.writes == expected);
    assert(uart.writeReady("00112233445566778899aabbccddeeff"));
    assert(io.bytes == "\r\nRGPU_UART_READY v=1 b=00112233445566778899aabbccddeeff port=2\r\n");
}

static void testAbsentUartRefusesOutput() {
    FakeIo io;
    io.absent = true;
    Uart uart(io);
    assert(!uart.initialize());
    assert(!uart.writeReady("00112233445566778899aabbccddeeff"));
    assert(io.bytes.empty());
}

static void testReadinessHonorsRemainingWorkerBudget() {
    FakeIo io;
    io.wireUsPerByte = 10;
    Uart uart(io);
    assert(uart.initialize());
    assert(!uart.writeReady("00112233445566778899aabbccddeeff", 25));
    assert(uart.failed());
    assert(io.now == 30);
    assert(io.bytes == "\r\nR");
    assert(io.bytes.find("RGPU_UART_READY") == std::string::npos);
}

static void testByteTimeoutLatchesAndOmitsEnd() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    io.bytes.clear();
    io.stallAt = 0;
    uart.beginSnapshot();
    uart("RGPU_CR2 first");
    assert(uart.failed());
    assert(io.now == Uart::kByteTimeoutUs);
    uart("RGPU_END2 must-not-appear");
    assert(io.bytes.empty());
}

static void testTotalDeadlineTruncatesAndNextAttemptRetries() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    io.bytes.clear();
    uart.beginSnapshot(25);
    io.stallAt = 0;
    uart("RGPU_CR2 blocked");
    assert(uart.failed());
    assert(io.now == 30); // 10 us polls never exceed the first poll after the deadline.
    uart("RGPU_END2 omitted");
    assert(io.bytes == "\r\n");

    io.stallAt = UINT64_MAX;
    assert(uart.initialize());
    uart.beginSnapshot();
    uart("RGPU_END2 retry");
    assert(!uart.failed());
    assert(io.bytes == "\r\n\r\nRGPU_END2 retry\r\n");
}

static void testPartialLineIsDelimitedBeforeRetry() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    io.bytes.clear();
    io.wireUsPerByte = 10;
    io.stallAt = 30;
    uart.beginSnapshot();
    uart("RGPU_CR2 partial");
    assert(uart.failed());
    assert(io.bytes == "\r\nR");

    io.stallAt = UINT64_MAX;
    assert(uart.initialize());
    uart.beginSnapshot();
    uart("RGPU_CR2 retry");
    assert(io.bytes.find("\r\nR\r\nRGPU_CR2 retry\r\n") != std::string::npos);
}

static void testMaximumFormatterSnapshotFitsDeadline() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    io.bytes.clear();
    io.wireUsPerByte = 87; // ceil(10 bits / 115200 baud), conservatively.
    uart.beginSnapshot();
    auto read = [](size_t, char (&out)[CR::kRecordStorageBytes]) {
        std::memset(out, 'X', sizeof(out));
        out[sizeof(out) - 1] = '\0';
        return true;
    };
    assert(CR::emitSnapshot("00112233445566778899aabbccddeeff", 0,
                            CR::kMaximumRecords, 0, 0, read,
                            [&](const char *line) { uart(line); }));
    assert(!uart.failed());
    assert(io.bytes.size() <= Uart::kMaximumSnapshotWireBytes);
    assert(io.now == io.bytes.size() * io.wireUsPerByte);
    assert(io.now < Uart::kSnapshotTimeoutUs);
    assert(io.bytes.find("RGPU_END2") != std::string::npos);
    uint64_t hash = UINT64_C(0xcbf29ce484222325);
    for (uint8_t byte : io.bytes) {
        hash ^= byte;
        hash *= UINT64_C(0x100000001b3);
    }
    assert(hash == UINT64_C(0xc4dc5b2650dfb248));
}

static void testFormatterOutputIsByteExactAndRetryIsLineDelimited() {
    static constexpr const char *build = "00112233445566778899aabbccddeeff";
    auto read = [](size_t sequence, char (&out)[CR::kRecordStorageBytes]) {
        if (sequence != 0) return false;
        std::memset(out, 0, sizeof(out));
        std::memcpy(out, "abc", 3);
        return true;
    };
    std::vector<std::string> reference;
    assert(CR::emitSnapshot(build, 7, 1, 0, 0, read,
                            [&](const char *line) { reference.emplace_back(line); }));

    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    uart.beginSnapshot();
    assert(CR::emitSnapshot(build, 7, 1, 0, 0, read,
                            [&](const char *line) { uart(line); }));
    std::string expected = "\r\n";
    for (const auto &line : reference) expected += line + "\r\n";
    assert(io.bytes == expected);

    io.bytes.clear();
    io.wireUsPerByte = 10;
    io.stallAt = 30;
    uart.beginSnapshot();
    assert(CR::emitSnapshot(build, 8, 1, 0, 0, read,
                            [&](const char *line) { uart(line); }));
    assert(uart.failed());
    assert(io.bytes.find("RGPU_END2") == std::string::npos);
    io.stallAt = UINT64_MAX;
    assert(uart.initialize());
    uart.beginSnapshot();
    assert(CR::emitSnapshot(build, 9, 1, 0, 0, read,
                            [&](const char *line) { uart(line); }));
    std::vector<std::string> retryReference;
    assert(CR::emitSnapshot(build, 9, 1, 0, 0, read,
                            [&](const char *line) { retryReference.emplace_back(line); }));
    std::string retryBytes = "\r\n";
    for (const auto &line : retryReference) retryBytes += line + "\r\n";
    size_t completeEnds = 0;
    size_t position = 0;
    while ((position = io.bytes.find("RGPU_END2", position)) != std::string::npos) {
        ++completeEnds;
        ++position;
    }
    assert(completeEnds == 1);
    const size_t failedFragment = io.bytes.find("\r\nR");
    assert(failedFragment != std::string::npos);
    assert(io.bytes.substr(failedFragment + 3) == retryBytes);
}

static void testHealthyAttemptsDoNotResetTheFifo() {
    FakeIo io;
    Uart uart(io);
    assert(uart.initialize());
    assert(uart.writeReady("00112233445566778899aabbccddeeff"));
    const size_t initializationWrites = io.writes.size();
    uart.beginSnapshot();
    uart("RGPU_CR2 healthy");
    assert(!uart.failed());
    // Starting another healthy attempt writes only stream bytes. In particular,
    // it does not issue FCR=0x07 and clear a still-buffered prior line.
    for (size_t i = initializationWrites; i < io.writes.size(); ++i)
        assert(io.writes[i].first == 0x2f8);
    assert(io.bytes.find("RGPU_UART_READY") < io.bytes.find("RGPU_CR2 healthy"));
}

int main() {
    testWorkerBudgetCapsDelayAndReadiness();
    testInitializationOrderAndReadiness();
    testAbsentUartRefusesOutput();
    testReadinessHonorsRemainingWorkerBudget();
    testByteTimeoutLatchesAndOmitsEnd();
    testTotalDeadlineTruncatesAndNextAttemptRetries();
    testPartialLineIsDelimitedBeforeRetry();
    testMaximumFormatterSnapshotFitsDeadline();
    testFormatterOutputIsByteExactAndRetryIsLineDelimited();
    testHealthyAttemptsDoNotResetTheFifo();
}
