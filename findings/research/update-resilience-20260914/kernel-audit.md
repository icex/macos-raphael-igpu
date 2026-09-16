# Raphael update resilience and kernel-only route audit — 2026-09-14

Scope was read-only. No project files, guests, GPU state, or hardware were changed.

## Observed current result

Candidate230 fixed the tested managed texture mismatch twice through an opt-in
current-task private COW delivery path. The current worktree `status.md` records
the exact runs, UUID/site matches, 96 copy cases, 122,548,224 pixel comparisons,
and zero mismatches. That is evidence for the 24G830 userspace image and the
guarded delivery mechanism. It is not update resilience: the source still depends
on the 24G830 Metal-driver UUID/site and the 24G830 X6000 kext route.

## KDK and UUID inventory

The only complete driver binary found in the active evidence tree is:

`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`

It is Mach-O 64-bit (`0xfeedfacf`), has nine load commands, and LC_UUID
`72574de596463f51ac2eadf626b4093b`; SHA-256 is
`2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`.
The available `candidate-182/183/191-preflight-harness/kdk` directories do not
contain additional AMDRadeonX6000 binaries. The disassembly evidence is therefore
one 24G830-era image, not a cross-version offset study. The Metal image UUID in
the existing parser/evidence is `906f11a39daf35bdb8eacfd2160fae1a`.

## Symbol resolver and fixed-offset boundary

Correction to an earlier draft: Lilu `KernelPatcher::solveSymbol(size_t id, ...)`
resolves symbols from the loaded `kinfo` identified by `id`, not only from the
kernel. The header documents “loaded kinfo id” at
`/home/bogdan/macos-vm/build/Lilu-1.6.8/Lilu/Headers/kern_patcher.hpp:195`; the
implementation calls `kinfos[id]->solveSymbol(symbol)` at
`Lilu/Sources/kern_patcher.cpp:213`. WhateverGreen uses this for loaded Radeon
kexts: `ref/WhateverGreen/WhateverGreen/kern_rad.cpp:294` resolves
`_dce_driver_set_backlight` with `patcher.solveSymbol(index, ...)`, and lines
284–292 route named functions with `routeMultiple(index, ..., address, size, ...)`.
The current callback has the X6000 `index`, `addr`, and `sz`, so a symbol route is
technically available. The same implementation is also present in upstream
`https://raw.githubusercontent.com/acidanthera/WhateverGreen/master/WhateverGreen/kern_rad.cpp`.
The exact mangled symbol is present in the offline KDK symbols:

`/tmp/claude-1000/-home-bogdan-src-macos-raphael-igpu/015b73f8-2b58-4b71-acd8-e47ac36b2820/scratchpad/re/kext_syms.txt:860`

`__ZN29AMDRadeonX6000_AMDAccelDevice15getHardwareInfoEP24_sAMD_GET_HW_INFO_VALUES`
at VMA `0xeca4`. A runtime attempt can therefore use
`patcher.solveSymbol(index, symbol, addr, sz)` and safely skip on zero, range
failure, ABI/prologue mismatch, or failed route construction.

The existing X6000 offsets are broad: hardware/VM routes at `src/RaphaelGPU.cpp`
around lines 725–765, AlignManager2 at `0x6032a`, preferred swizzle at `0x60566`,
and the diagnostic getHardwareInfo route at `0xeca4`. They are all tied to the
same pinned X6000 image. A future OS can preserve names while changing VMA,
prologue, ABI, object layout, or call graph; an exact mangled name alone does not
make the route update-safe.

The update-resilient route is therefore to try the loaded-kinfo symbol first,
constrain it to `[addr, addr+sz)`, validate ABI/prologue and displaced instructions,
and refuse stripped or unknown images. UUID/signature metadata remains useful for
semantic validation, but a new memory symbol-table parser is not required merely
to locate this method.

## Kernel hardware-info and AddrLib path

The concrete native path is present in the existing disassembly:

* `AMDAccelDevice::getHardwareInfo` `0xeca4` copies a 0x204-byte hardware-info
  result to its output (`kext_text.dis`, corresponding symbol above).
* `AMDHWAlignManager2::init` `0x6032a` consumes the hardware-info block; the
  existing source documents the getter slot `+0x1c0` and `gbAddrConfig` field
  `hwinfo+0xa0` (`src/RaphaelGPU.cpp:3904–3925`).
* The kernel AddrLib methods are actual exported symbols in the offline kext:
  `getPreferredSwizzleMode2` `0x60566`, `getSurfaceInfo2` `0x60620`, and
  `getSurfaceInfo` `0x608dc` (`kext_syms_sorted.txt:3651–3653`).
* IOUserClient surface-copy dispatch is separate: `SurfaceCopy` `0x214d4`,
  `AMDAccelSharedUserClient::SurfaceCopy` `0x2276a`, and resource descriptor
  construction `fillUBMSurfaceInfo` `0x17010`. GFX10 paths include
  `fillUBMSurfaceInfoInternal` `0x3d412`/Addr2 `0x1feaa`; token texture-copy
  processing calls `SetupUBMSurfInfoFromTokenSurfInfo` `0x4199c` from
  `process_StretchTex2Tex` `0x3e864`.

These facts establish a possible native metadata intervention point, but not the
needed field. The current source's `rgpuaddrcfg` hook can replace `hwinfo+0xa0`
with live `GB_ADDR_CONFIG`; prior evidence says the `0x42` SDMA/desktop correction
does not repair the large managed texture copy mismatch. The userspace bit27
change fixes both producer and consumer because the Metal driver uses its own
settings-derived pipe-bank-xor behavior. No evidence ties that setting bit to a
kernel hardware-info field or proves that changing UBM `+0x230` at one kernel
descriptor builder reaches every managed upload, synchronize, and private copy
producer/consumer pair.

Thus the kernel metadata route remains an open hypothesis, not an exhausted route
and not a demonstrated alternative. The strongest concrete kernel candidate is a
versioned hook around the actual per-resource UBM descriptor builders (`0x17010`,
`0x3d412`, `0x1feaa`) that logs and, only after dataflow proof, normalizes the
same swizzle/pipe-bank-xor field for both sides. Fixed offset alone cannot make it
update-resilient.

## Smallest discriminating offline/next-version test

For each new OS image, first extract its X6000 and Metal LC_UUIDs and disassemble
only the named functions and their callers. Reject the route if the exact symbol,
ABI, or descriptor field cannot be proven. If they match, instrument or compare
the UBM surface descriptors for one failing managed upload and one synchronize:
the test must show whether both descriptors carry a common kernel-controlled
swizzle field. Equalizing that field in a controlled kernel-only hook and observing
both directions become correct would establish a native alternative. If the fields
are already equal while the mismatch remains, the kernel metadata hypothesis is
falsified for that image and the userspace setting remains the causal lever.

## Bounded conclusion

Observed evidence supports a guarded current-task userspace-byte delivery fix for
one pinned 24G830 image. Available artifacts do not contain multiple KDK versions,
and the loaded-kinfo symbol resolver has not yet been tried for this method. A
symbol-first route is a concrete update-resilience improvement over `0xeca4`,
subject to stripped-symbol and ABI validation. A UUID/signature database plus
refusal on unknown images remains the safe behavior when those checks fail. A
native metadata fix is technically
plausible at the documented UBM/AddrLib boundaries but remains unresolved until
descriptor dataflow proves one common kernel-owned field controls both producers
and consumers.
