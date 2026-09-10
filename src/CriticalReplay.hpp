#pragma once

#include <stddef.h>
#include <stdint.h>

namespace rgpu {
namespace CriticalReplayV2 {

static constexpr size_t kRecordStorageBytes = 512;
static constexpr size_t kMaximumRecords = 512;
static constexpr size_t kChunkBytes = 40;
static constexpr size_t kMaximumChunksPerRecord = 13;
static constexpr size_t kMaximumChunkLineCharacters = 172;
static constexpr size_t kMaximumEndLineCharacters = 206;
static constexpr size_t kRenderedSyslogPrefixBytes = 24;
static constexpr size_t kWireBufferBytes = kMaximumEndLineCharacters + 1;

static_assert(kRenderedSyslogPrefixBytes + kMaximumEndLineCharacters + 1 < 240,
              "critical replay physical lines must remain below 240 bytes");

inline uint32_t crc32Update(uint32_t state, const uint8_t *bytes, size_t size) {
    for (size_t i = 0; i < size; ++i) {
        state ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            state = (state >> 1) ^ (0xedb88320u & (0u - (state & 1u)));
    }
    return state;
}

inline uint64_t fnv1a64Update(uint64_t state, const uint8_t *bytes, size_t size) {
    for (size_t i = 0; i < size; ++i) {
        state ^= bytes[i];
        state *= UINT64_C(0x100000001b3);
    }
    return state;
}

inline void updateLe32(uint32_t &crc, uint64_t &fnv, uint32_t value) {
    uint8_t bytes[4];
    for (size_t i = 0; i < sizeof(bytes); ++i)
        bytes[i] = static_cast<uint8_t>(value >> (i * 8));
    crc = crc32Update(crc, bytes, sizeof(bytes));
    fnv = fnv1a64Update(fnv, bytes, sizeof(bytes));
}

inline void updateLe64(uint32_t &crc, uint64_t &fnv, uint64_t value) {
    uint8_t bytes[8];
    for (size_t i = 0; i < sizeof(bytes); ++i)
        bytes[i] = static_cast<uint8_t>(value >> (i * 8));
    crc = crc32Update(crc, bytes, sizeof(bytes));
    fnv = fnv1a64Update(fnv, bytes, sizeof(bytes));
}

inline int hexNibble(char ch) {
    if (ch >= '0' && ch <= '9') return ch - '0';
    if (ch >= 'a' && ch <= 'f') return ch - 'a' + 10;
    return -1;
}

inline bool decodeBuildId(const char *text, uint8_t (&bytes)[16]) {
    if (text == nullptr) return false;
    for (size_t i = 0; i < sizeof(bytes); ++i) {
        if (text[i * 2] == '\0') return false;
        const int high = hexNibble(text[i * 2]);
        if (text[i * 2 + 1] == '\0') return false;
        const int low = hexNibble(text[i * 2 + 1]);
        if (high < 0 || low < 0) return false;
        bytes[i] = static_cast<uint8_t>((high << 4) | low);
    }
    return text[32] == '\0';
}

class LineWriter {
    char *out_;
    size_t capacity_;
    size_t length_ {};
    bool valid_ {true};

public:
    LineWriter(char *out, size_t capacity) : out_(out), capacity_(capacity) {
        if (capacity_ != 0) out_[0] = '\0';
    }

    void character(char value) {
        if (!valid_ || length_ + 1 >= capacity_) { valid_ = false; return; }
        out_[length_++] = value;
        out_[length_] = '\0';
    }

    void literal(const char *value) {
        for (size_t i = 0; value[i] != '\0'; ++i) character(value[i]);
    }

    void hex(uint64_t value, unsigned width) {
        static constexpr char digits[] = "0123456789abcdef";
        for (unsigned i = width; i > 0; --i)
            character(digits[(value >> ((i - 1) * 4)) & 0xf]);
    }

    void bytes(const uint8_t *value, size_t size) {
        for (size_t i = 0; i < size; ++i) hex(value[i], 2);
    }

    bool valid() const { return valid_; }
    size_t length() const { return length_; }
};

inline bool recordLength(const char (&record)[kRecordStorageBytes], size_t &length) {
    for (length = 0; length < sizeof(record); ++length) {
        const uint8_t byte = static_cast<uint8_t>(record[length]);
        if (byte == 0) return true;
        if (byte < 0x20 || byte > 0x7e) return false;
    }
    return false;
}

inline uint32_t chunkCrc(const uint8_t (&build)[16], uint32_t snapshot,
                         uint16_t record, uint8_t part, uint8_t parts,
                         const uint8_t *payload, uint8_t length) {
    uint32_t crc = UINT32_C(0xffffffff);
    const uint8_t version = 1;
    crc = crc32Update(crc, &version, 1);
    crc = crc32Update(crc, build, sizeof(build));
    uint64_t ignoredFnv = 0;
    updateLe32(crc, ignoredFnv, snapshot);
    uint8_t fields[5] {
        static_cast<uint8_t>(record), static_cast<uint8_t>(record >> 8),
        part, parts, length};
    crc = crc32Update(crc, fields, sizeof(fields));
    crc = crc32Update(crc, payload, length);
    return crc ^ UINT32_C(0xffffffff);
}

inline bool formatChunkLine(char (&line)[kWireBufferBytes], const char *buildText,
                            const uint8_t (&build)[16], uint32_t snapshot,
                            uint16_t record, uint8_t part, uint8_t parts,
                            const uint8_t *payload, uint8_t length) {
    LineWriter writer(line, sizeof(line));
    writer.literal("RGPU_CR2 v=1 b="); writer.literal(buildText);
    writer.literal(" s="); writer.hex(snapshot, 8);
    writer.literal(" r="); writer.hex(record, 4);
    writer.literal(" p="); writer.hex(part, 2); writer.character('/'); writer.hex(parts, 2);
    writer.literal(" n="); writer.hex(length, 2);
    writer.literal(" c=");
    writer.hex(chunkCrc(build, snapshot, record, part, parts, payload, length), 8);
    writer.literal(" d="); writer.bytes(payload, length);
    return writer.valid() && writer.length() <= kMaximumChunkLineCharacters;
}

inline void checksumBytes(uint32_t &crc, uint64_t &fnv,
                          const uint8_t *bytes, size_t size) {
    crc = crc32Update(crc, bytes, size);
    fnv = fnv1a64Update(fnv, bytes, size);
}

inline bool formatEndLine(char (&line)[kWireBufferBytes], const char *buildText,
                          uint32_t snapshot, uint16_t count, uint64_t dropped,
                          uint64_t truncated, uint32_t bytes, uint32_t chunks,
                          uint32_t crc, uint64_t fnv) {
    LineWriter writer(line, sizeof(line));
    writer.literal("RGPU_END2 v=1 b="); writer.literal(buildText);
    writer.literal(" s="); writer.hex(snapshot, 8);
    writer.literal(" first=0000 count="); writer.hex(count, 4);
    writer.literal(" drop="); writer.hex(dropped, 16);
    writer.literal(" trunc="); writer.hex(truncated, 16);
    writer.literal(" bytes="); writer.hex(bytes, 8);
    writer.literal(" chunks="); writer.hex(chunks, 8);
    writer.literal(" crc="); writer.hex(crc, 8);
    writer.literal(" fnv="); writer.hex(fnv, 16);
    writer.literal(" state=complete");
    return writer.valid() && writer.length() <= kMaximumEndLineCharacters;
}

template <typename ReadRecord, typename EmitLine>
bool emitSnapshot(const char *buildText, uint32_t snapshot, size_t count,
                  uint64_t dropped, uint64_t truncated,
                  ReadRecord readRecord, EmitLine emitLine) {
    if (count > kMaximumRecords) return false;
    uint8_t build[16];
    if (!decodeBuildId(buildText, build)) return false;

    // Preflight every immutable slot before emitting the first physical line.
    // A producer may have reserved the final slot without publishing it yet.
    uint32_t totalBytes = 0;
    uint32_t totalChunks = 0;
    for (size_t sequence = 0; sequence < count; ++sequence) {
        char record[kRecordStorageBytes];
        size_t length = 0;
        if (!readRecord(sequence, record) || !recordLength(record, length)) return false;
        totalBytes += static_cast<uint32_t>(length);
        totalChunks += static_cast<uint32_t>(length == 0 ? 1 :
            (length + kChunkBytes - 1) / kChunkBytes);
    }

    uint32_t snapshotCrc = UINT32_C(0xffffffff);
    uint64_t snapshotFnv = UINT64_C(0xcbf29ce484222325);
    static constexpr uint8_t domain[] = {'R','G','P','U','-','C','R','2',0};
    checksumBytes(snapshotCrc, snapshotFnv, domain, sizeof(domain));
    const uint8_t version = 1;
    checksumBytes(snapshotCrc, snapshotFnv, &version, 1);
    checksumBytes(snapshotCrc, snapshotFnv, build, sizeof(build));
    updateLe32(snapshotCrc, snapshotFnv, snapshot);
    uint8_t prefix[4] {0, 0, static_cast<uint8_t>(count),
                       static_cast<uint8_t>(count >> 8)};
    checksumBytes(snapshotCrc, snapshotFnv, prefix, sizeof(prefix));
    updateLe64(snapshotCrc, snapshotFnv, dropped);
    updateLe64(snapshotCrc, snapshotFnv, truncated);
    updateLe32(snapshotCrc, snapshotFnv, totalBytes);
    updateLe32(snapshotCrc, snapshotFnv, totalChunks);

    for (size_t sequence = 0; sequence < count; ++sequence) {
        char record[kRecordStorageBytes];
        size_t length = 0;
        if (!readRecord(sequence, record) || !recordLength(record, length)) return false;
        uint8_t recordHeader[4] {
            static_cast<uint8_t>(sequence), static_cast<uint8_t>(sequence >> 8),
            static_cast<uint8_t>(length), static_cast<uint8_t>(length >> 8)};
        checksumBytes(snapshotCrc, snapshotFnv, recordHeader, sizeof(recordHeader));
        checksumBytes(snapshotCrc, snapshotFnv,
                      reinterpret_cast<const uint8_t *>(record), length);

        const uint8_t parts = static_cast<uint8_t>(length == 0 ? 1 :
            (length + kChunkBytes - 1) / kChunkBytes);
        for (uint8_t part = 0; part < parts; ++part) {
            const size_t offset = static_cast<size_t>(part) * kChunkBytes;
            const uint8_t partLength = static_cast<uint8_t>(
                offset < length && length - offset > kChunkBytes ?
                    kChunkBytes : (offset < length ? length - offset : 0));
            char line[kWireBufferBytes];
            if (!formatChunkLine(line, buildText, build, snapshot,
                                 static_cast<uint16_t>(sequence), part, parts,
                                 reinterpret_cast<const uint8_t *>(record) + offset,
                                 partLength)) return false;
            emitLine(line);
        }
    }

    snapshotCrc ^= UINT32_C(0xffffffff);
    char line[kWireBufferBytes];
    if (!formatEndLine(line, buildText, snapshot, static_cast<uint16_t>(count),
                       dropped, truncated, totalBytes, totalChunks,
                       snapshotCrc, snapshotFnv)) return false;
    emitLine(line);
    return true;
}

} // namespace CriticalReplayV2
} // namespace rgpu
