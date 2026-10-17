# Dynamic texture-fix discovery investigation

2026-09-14. Offline investigation only. No GPU launch, driver deployment, OS
update, disk patch or security-setting change. Last tested candidate230 remains
staged; no VM is running. Host boot c369c74e-96ff-4c21-ae85-80ccb269f7d2.

## Conclusion

The private-COW delivery mechanism is usable; its exact-build discovery is
unnecessarily restrictive. A metadata-assisted structural locator plus a
symbol-resolved kernel callback is a concrete route toward automatic handling of
compatible driver updates. The investigation does not establish support for a
second macOS build, or make the entire RaphaelGPU driver update-safe.

Candidate230 should remain the known working fallback until the dynamic path
has been integrated and checked against real additional driver versions. Simply
removing its UUID check and scanning for the old ten bytes is insufficient.

## Concrete discoveries

1. The real Metal __TEXT contains a named `AMD_DeviceSettings` encoding in
   `__objc_methtype`. `enableTexturePipeBankXor` occurs among contiguous bitfields;
   parsing their widths derives bit27, independently of the old instruction
   offset and UUID. The relevant encoding begins at offset0x4d7ea1 in this image.
   The string is metadata, not a supported runtime configuration interface.
2. The constructor builds its output in `[rdi]`; `rsi` is hardware-info input.
   Reads at `[rsi+0xa0]` are hardware capabilities, not a settings-object offset.
   A bounded MOV-immediate/OR/store sequence can be located structurally, with
   neighboring capability synthesis checked. The prototype finds the correct
   instruction at0x13a7e1 and computes the one-byte change at0x13a7e6 without
   those offsets, UUID, full immediate, or hardcoded bit27 in locator logic.
3. Lilu already exposes `solveSymbol(kinfo_id, name, range...)` for loaded kexts.
   The callback can be resolved by its mangled getHardwareInfo symbol within the
   current X6000 image, instead of `base+0xeca4`. WhateverGreen uses this public
   kext-index API and symbol-based Radeon routes. Symbol availability, ABI,
   bounds and trampoline safety still need validation. An initial delegated
   claim that solveSymbol was kernel-only was disproved and corrected.
4. Native UBM/AddrLib producer-consumer metadata correction remains unresolved.
   No new kernel-owned field has been demonstrated to fix both managed paths.
   That is not proof of impossibility and does not justify claiming a native
   kernel-only fix from the successful COW tests.

Primary source for kext symbol routing:
[WhateverGreen Radeon implementation](https://raw.githubusercontent.com/acidanthera/WhateverGreen/master/WhateverGreen/kern_rad.cpp)
and [Lilu KernelPatcher API](https://raw.githubusercontent.com/acidanthera/Lilu/master/Lilu/Headers/kern_patcher.hpp).

## Read-only prototype evidence

`locate_texture_setting.py` parses sections, derives the named field position,
scans only __text, validates a narrow instruction family and requires one match.
It reports a proposed byte/mask; it never writes an image or guest memory.
Capstone5.0.7 was used via an isolated uv environment.

Eleven checks passed in `locator-results.json`: one real 24G830 image and ten
synthetic cases. These cover a changed UUID, changed unrelated default bit,
already-disabled bit, metadata bit-layout shift, moved constructor window,
duplicate candidate refusal, missing named metadata refusal, changed OR dataflow
refusal, non-code lookalike rejection and truncated-image refusal.

These mutations are not executable replacement OS builds. A structural match
is not a full proof linking the named setting to the constructor's output:
compiler changes, field packing changes, register allocation and new instruction
forms still need decoding/dataflow support. The prototype currently supports
only the observed constructor family and a first-word target bit. It must not
replace the production UUID guard yet. No second independent OS image was found
locally; copies of the same KDK are not cross-version evidence.

Input: archived real __TEXT,5253550bytes, SHA256
edea49f14138e3d017dd4e910db94ef19fcb708b3f31e178c208706a7b5da88d.
Reproduce with:

```
uv run --with capstone==5.0.7 python test_locator.py /path/to/mtl__TEXT.bin
```

## Recommended implementation and update behavior

- Resolve the kernel callback by name and validate its current ABI/route range.
- Locate the setting by named metadata plus independently checked constructor
  dataflow; use image UUID as provenance/cache identity, not a universal address
  whitelist. Cache a verified image-relative result, never a stale ASLR address.
- Preserve other defaults by clearing only the derived bit in the live immediate;
  recognize already-cleared defaults and ambiguous/unsupported code separately.
- Retain the tested per-task COW, byte revalidation and active-permission restore.
- Add an automatic compatibility result that distinguishes discovered, applied,
  already-disabled and unsupported. Qualify new driver images with the existing
  two-way managed-copy matrix and native-path/capture/recovery checks. Never
  promote a synthetic locator pass to a hardware compatibility claim.

| Update | Expected handling |
|---|---|
| AMD binaries unchanged | Existing image-based patch may already work; changing OS version alone does not imply a new target |
| Same supported code family moved/rebuilt | Dynamic locator can rediscover and derive the mask; shown only with synthetic mutations so far |
| Compiler/metadata/ABI materially changed | Refuse unsupported structure; extend/revalidate the resolver |
| Kernel graphics interfaces changed | Port the affected RaphaelGPU hooks as well; the texture locator cannot solve this |

The current source contains84 `static constexpr size_t kOff...` declarations,
including diagnostics and other hooks (not84 active mandatory patches), and
PluginConfiguration declares Catalina through Sequoia support. The full driver
therefore needs a separate active-hook compatibility inventory before major-OS
support can be claimed. No private-driver patch can honestly guarantee arbitrary
future Apple ABI changes will require zero maintenance.
