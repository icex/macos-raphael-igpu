#pragma once
#include <stdint.h>
#include <stddef.h>
namespace RaphaelVcnDpg {
// Linux RREG32_SOC15_DPG_MODE: index is already a DWORD register address.
// Only select READ (bit0 clear), never replay a saved write-command control.
// Validate the complete image before touching the port. Report final writes
// for duplicate registers; no interpretation of inaccessible readback values.
template<class WriteControl, class ReadData, class Report>
bool readback(const uint32_t *image, size_t bytes, WriteControl write,
              ReadData read, Report report) {
    if (!image || bytes == 0 || bytes > 512 || bytes % 8) return false;
    const size_t words = bytes / 4;
    for (size_t i = 0; i < words; i += 2)
        if (image[i] > 0xffff) return false;
    for (size_t i = 0; i < words; i += 2) {
        bool final = true;
        for (size_t j = i + 2; j < words; j += 2)
            if (image[j] == image[i]) final = false;
        if (!final) continue;
        write(image[i] << 16);
        const uint32_t observed = read();
        report(image[i], image[i+1], observed);
    }
    write(0); // leave the port in read mode, without altering SRAM data
    return true;
}
}
