# Managed-texture-copy defect: fix proven, delivery blocked on Sequoia (2026-09-14)

## Status
- **Desktop Metal acceleration is functionally achieved**: the desktop composites correctly
  (SDMA0_GB_ADDR_CONFIG 0x444->0x42 fix, rgpusdmacfg=2), offscreen rendering is exact
  (0 mismatches), and all readback paths are correct EXCEPT one.
- **Residual defect**: MTLStorageModeManaged 2D-texture tiled<->linear copies at large size
  (1280x1024): `private->managed-texture+sync` and `upload managed-texture->private` each
  1,310,720 bytes wrong (one pipe-bank-xor bit at 64px). 64x64 and all buffer/render paths
  are correct.
- **The fix is PROVEN**: clearing enableTexturePipeBankXor (AMD_DeviceSettings bit 27) in
  AMDRadeonX6000MTLDriver fixes both paths while keeping tiling (probe v7/v9 self-patch child
  `linearswizzle1`/`pipebankxor0` fix every path, reproduced every run incl. candidate 227/228).
- **Decision (user, 2026-09-14): accept the current state and document the limitation.** No
  clean, safe delivery of the bit-27 patch exists on stock sealed Sequoia.

## Why there is no clean delivery (all paths exhausted, two independent agents + on-hardware)
1. **Not a kernel-kext fix.** The blit and the synchronize/retile are userspace Metal compute
   shaders (amdMtl_CopyFromTextureToTexture; metadataRetile with Gfx10RetileParams.gfxPipeBankXor
   as a shader arg) driven by a userspace AMD_TextureParamsRec; the kernel never sees the texture
   pipeBankXor. kernel doSurfaceCopy is an empty stub; fillUBMSurfaceInfoInternal is bypassed by
   the failing blit paths; forcing kernel getPreferredSwizzleMode2->linear (rgpuswlog=2) fixed the
   drawable but not textures. See [kernel-surfinfo-fix-investigation-20260914.md].
2. **No config knob.** Full disassembly of the driver's settings init: bits 27/29/36 are set only
   by hardcoded immediates/masks in one constructor. The ~34 live env vars and all ASIC-capability
   fields never touch 27/29/36. No IORegistry/plist/property read feeds the settings word, so an
   OpenCore DeviceProperties injection cannot flip them. The only name-based setter
   (/AmdMtlSettingsFile.txt parser) is dead code (0 refs). Confirmed.
3. **Lilu userspace patcher is a dead end on Sequoia.** Lilu disables its whole user patcher on
   macOS >= Big Sur (isUserDisabled). We built our own Lilu with a fileless shared-cache patch
   (BinaryModInfo::filelessSegOffs + unslid __TEXT base 0x7ffb08bf3000, bypassing the dyld .map);
   the kext registers the patch (onProcLoad -> 0) but it never runs because the patcher is disabled
   (candidate 227 e9915a03, candidate 228 1df50f51: both CORE_PROBE_PASS, defect unchanged, no
   patcher activity). Forcing isUserDisabled=false is UNSAFE and likely futile on 24G830 (XNU-11417):
   `_vm_shared_region_slide` needs >=9 args (Lilu hook 7) and `_vm_shared_region_map_file` >=12
   (hook 9) -> forwarding garbage -> panic vector; the one-time region slide is set up by launchd
   before Lilu's patcher init so the slide is never captured -> injectRestrict() damages
   WindowServer instead; vmProtect's p_csflags heuristic uses a stale 2018 struct-proc offset.

## What WOULD deliver it (for the future; each has a real cost, all declined for now)
- **On-disk shared-cache patch (guest surgery)**: flip ff->f7 at the driver's movabs in the guest's
  dyld shared cache (Cryptex), disable authenticated-root / handle AMFI, re-bless. Persistent; boot
  risk; VM rebuildable. Cleanest "fix the driver", no runtime hacking.
- **Kernel per-process patch in our kext**: hook each process's first AMD-accelerator call and
  vm_write ff->f7 into that process's own driver copy (correct timing, targeted). Hand-rolled
  cross-process memory patching; blocked by the session's auto-mode safety classifier; the user had
  earlier preferred not to runtime-patch the Metal driver.
- **Fix Lilu's shared-region hook prototypes** to XNU-11417 arity + validate csFlagsOffset + confirm
  slide capture. Multi-cycle RE, panic risk, and the slide is likely never captured (region set up
  before Lilu init) -> low odds.

## Exact patch site (if ever delivered)
AMDRadeonX6000MTLDriver __TEXT, KDK 24G830, unslid base 0x7ffb08bf3000:
- offset 0x13a7e1: `48 b8 00 00 70 ff 01 00 00 00` (movabs rax,0x1ff700000) -> `...70 f7...`
  clears bit 27 (enableTexturePipeBankXor). Unique in __TEXT.
- (alt) offset 0x13a82b sets linearSwizzleTextures bit 36 (byte+6 e0->f0) -> fixes all paths.
