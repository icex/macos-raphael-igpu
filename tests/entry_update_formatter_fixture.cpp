#include "src/VmEntryUpdate.hpp"

#include <cstdio>
#include <cstdlib>

#define FIXTURE_CRLOG(format, ...) std::printf("%s" format "\n", "", __VA_ARGS__)

int main(int argc, char **argv) {
    if (argc != 2 && argc != 17) return 2;
    const uint32_t mode = static_cast<uint32_t>(std::strtoul(argv[1], nullptr, 10));
    uint64_t counts[RaphaelVm::kUpdateDomainCount] = {0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0};
    uint64_t omitted[3] {};
    uint32_t route = 1;
    if (argc == 17) {
        route = static_cast<uint32_t>(std::strtoul(argv[2], nullptr, 10));
        for (size_t index = 0; index < RaphaelVm::kUpdateDomainCount; ++index)
            counts[index] = std::strtoull(argv[3 + index], nullptr, 10);
        for (size_t index = 0; index < 3; ++index)
            omitted[index] = std::strtoull(argv[14 + index], nullptr, 10);
    }
    FIXTURE_CRLOG(RGPU_VM_ENTRY_UPDATE_SUMMARY_FORMAT, mode, route,
                static_cast<unsigned long long>(counts[0]),
                static_cast<unsigned long long>(counts[1]),
                static_cast<unsigned long long>(counts[2]),
                static_cast<unsigned long long>(counts[3]),
                static_cast<unsigned long long>(counts[4]),
                static_cast<unsigned long long>(counts[5]),
                static_cast<unsigned long long>(counts[6]),
                static_cast<unsigned long long>(counts[7]),
                static_cast<unsigned long long>(counts[8]),
                static_cast<unsigned long long>(counts[9]),
                static_cast<unsigned long long>(counts[10]),
                static_cast<unsigned long long>(omitted[0]),
                static_cast<unsigned long long>(omitted[1]),
                static_cast<unsigned long long>(omitted[2]));
    return 0;
}
