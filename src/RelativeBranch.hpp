#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

namespace RaphaelRelativeBranch {
// Preserve the near-JE condition and compute its signed displacement from the
// discovered source/cleanup sites. Never reuse a displacement from another image.
inline bool redirectJe(const uint8_t *live, uintptr_t source, uintptr_t target,
                       uint8_t replacement[6]) {
    if (!live || !replacement || live[0] != 0x0f || live[1] != 0x84 ||
        !source || !target || source > UINTPTR_MAX-6) return false;
    const uintptr_t next=source+6;
    int32_t displacement=0;
    if (target>=next) {
        if (target-next>INT32_MAX) return false;
        displacement=static_cast<int32_t>(target-next);
    } else {
        const uintptr_t distance=next-target;
        if (distance>static_cast<uintptr_t>(INT32_MAX)+1) return false;
        displacement=distance==static_cast<uintptr_t>(INT32_MAX)+1 ? INT32_MIN :
                     -static_cast<int32_t>(distance);
    }
    replacement[0]=0x0f;replacement[1]=0x84;
    memcpy(replacement+2,&displacement,sizeof(displacement));
    return true;
}
}
