#include "../src/CriticalReplay.hpp"

#include <cassert>
#include <cstring>
#include <string>
#include <vector>

namespace CR = rgpu::CriticalReplayV2;

int main() {
    static constexpr const char *build = "00112233445566778899aabbccddeeff";
    const std::vector<std::string> records {
        "BUILD: identity=00112233445566778899aabbccddeeff",
        "XH2 ABORT reason=duplicate-pool nonce=0123456789abcdef_fedcba9876543210",
    };
    auto read = [&](size_t sequence, char (&out)[CR::kRecordStorageBytes]) {
        if (sequence >= records.size()) return false;
        std::memset(out, 0, sizeof(out));
        std::memcpy(out, records[sequence].data(), records[sequence].size());
        return true;
    };
    std::vector<std::string> lines;
    auto emit = [&](const char *line) { lines.emplace_back(line); };

    assert(CR::emitSnapshot(build, 0x1a2b3c4d, 2, 7, 3, read, emit));
    const std::vector<std::string> expected {
        "RGPU_CR2 v=1 b=00112233445566778899aabbccddeeff s=1a2b3c4d r=0000 p=00/02 n=28 c=fc75d7cf d=4255494c443a206964656e746974793d303031313232333334343535363637373838393961616262",
        "RGPU_CR2 v=1 b=00112233445566778899aabbccddeeff s=1a2b3c4d r=0000 p=01/02 n=08 c=217c59a7 d=6363646465656666",
        "RGPU_CR2 v=1 b=00112233445566778899aabbccddeeff s=1a2b3c4d r=0001 p=00/02 n=28 c=d53443e8 d=5848322041424f525420726561736f6e3d6475706c69636174652d706f6f6c206e6f6e63653d3031",
        "RGPU_CR2 v=1 b=00112233445566778899aabbccddeeff s=1a2b3c4d r=0001 p=01/02 n=1f c=0bb0d5e3 d=32333435363738396162636465665f66656463626139383736353433323130",
        "RGPU_END2 v=1 b=00112233445566778899aabbccddeeff s=1a2b3c4d first=0000 count=0002 drop=0000000000000007 trunc=0000000000000003 bytes=00000077 chunks=00000004 crc=00224176 fnv=d9b26014fb169578 state=complete",
    };
    assert(lines == expected);
    for (const auto &line : lines)
        assert(CR::kRenderedSyslogPrefixBytes + line.size() + 1 < 240);

    // A reserved but unpublished slot must suppress the whole attempt. Emitting
    // a partial prefix would turn normal producer preemption into capture loss.
    lines.clear();
    auto pending = [&](size_t sequence, char (&out)[CR::kRecordStorageBytes]) {
        if (sequence == 1) return false;
        return read(sequence, out);
    };
    assert(!CR::emitSnapshot(build, 2, 2, 0, 0, pending, emit));
    assert(lines.empty());

    // A line-breaking record and a malformed build identity cannot produce a
    // manifest that the host could mistake for a canonical complete snapshot.
    lines.clear();
    auto noncanonical = [&](size_t sequence, char (&out)[CR::kRecordStorageBytes]) {
        if (!read(sequence, out)) return false;
        if (sequence == 1) out[3] = '\n';
        return true;
    };
    assert(!CR::emitSnapshot(build, 3, 2, 0, 0, noncanonical, emit));
    assert(lines.empty());
    assert(!CR::emitSnapshot("00112233445566778899AABBCCDDEEFF", 4, 2, 0, 0,
                             read, emit));
    assert(lines.empty());
    char *shortBuild = new char[1] {'\0'};
    assert(!CR::emitSnapshot(shortBuild, 5, 2, 0, 0, read, emit));
    delete[] shortBuild;
    assert(lines.empty());

    // Cross-language boundary vector shared with the Python consumer. It also
    // exercises the maximum 511-byte record and 13-part chunk count.
    const std::vector<std::string> boundaryRecords {
        std::string(184, 'A'), std::string(511, 'B')};
    auto readBoundary = [&](size_t sequence, char (&out)[CR::kRecordStorageBytes]) {
        if (sequence >= boundaryRecords.size()) return false;
        std::memset(out, 0, sizeof(out));
        std::memcpy(out, boundaryRecords[sequence].data(), boundaryRecords[sequence].size());
        return true;
    };
    assert(CR::emitSnapshot("0123456789abcdef0123456789abcdef", 0x01020304,
                            2, 0, 0, readBoundary, emit));
    assert(lines.size() == 19);
    assert(lines[0].find("r=0000 p=00/05 n=28 c=5fb98dfd") != std::string::npos);
    assert(lines[4].find("r=0000 p=04/05 n=18 c=ea236aa2") != std::string::npos);
    assert(lines[17].find("r=0001 p=0c/0d n=1f c=d8065aa9") != std::string::npos);
    assert(lines[18] ==
        "RGPU_END2 v=1 b=0123456789abcdef0123456789abcdef s=01020304 "
        "first=0000 count=0002 drop=0000000000000000 trunc=0000000000000000 "
        "bytes=000002b7 chunks=00000012 crc=c8001837 fnv=2231439245f39550 "
        "state=complete");
}
