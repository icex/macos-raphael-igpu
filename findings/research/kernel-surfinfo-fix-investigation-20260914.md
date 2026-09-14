# Can the Managed-texture tiling defect be fixed in the KERNEL kext? (2026-09-14)

Context: user asked to check whether fillUBMSurfaceInfoInternal / doSurfaceCopy give a
kernel (our-driver) fix for the MTLStorageModeManaged 2D-texture pipe-bank-xor defect
before patching Apple's userspace Metal driver.

## Static RE of AMDRadeonX6000.kext (KDK, symbols)
- AMDTPTManager::doSurfaceCopy @0x2ddae and doBiDirSurfaceCopy @0x2ddb4 = EMPTY STUBS
  (push rbp/mov/pop/ret). Only doMemCopy @0x2ddba is real = plain CPU sysbuffer memcpy,
  no swizzle. => the doSurfaceCopy the user named is a dead end.
- AMDHWDisplay::fillUBMSurface @0x4ee8a = DISPLAY/scanout path (_FRAMEBUFFER_INFO), extracts
  swizzle=(desc>>0x19)&7 -> surfinfo+0x230; not Metal textures.
- AMDAccelResource::fillUBMSurfaceInfoInternal @0x1709c (GFX10Resource thunk @0x3d412 ->
  vtable[0x358]) = per-resource surfinfo builder; transcribes _ati_format_info_table +
  vtable[0x128] type checks; does NOT call addrlib.
- AMDGFX10GLContext::SetupUBMSurfInfoFromTokenSurfInfo @0x4199c transcribes a USERSPACE
  GFX10_SurfInfo token (r14) into _UBM_SURFINFO: surfinfo+0x230 = (token[0x8]>>18)&0x3f =
  SWIZZLE MODE (ADDR_SW_*; LINEAR=0). So the swizzle is chosen in userspace, transcribed here.

## Decisive existing on-hardware evidence (candidate 220)
- rgpuswlog=1: kernel getPreferredSwizzleMode2 IS called for 1280x1024 (returns mode 27).
- rgpuswlog=2 (force kernel addrlib -> LINEAR): fixed the CAMetalLayer DRAWABLE but left
  probe Metal TEXTURES unchanged/permuted. Recorded: "user space selects texture layouts
  itself." => kernel addrlib CHOICE path cannot fix Metal textures.
- probe v7 (metal-067): ONLY userspace AMDRadeonX6000MTLDriver constant patches fix them:
  clear enableTexturePipeBankXor(bit27) fixes managed-texture paths; set
  linearSwizzleTextures(bit36) fixes ALL. "None depends on kernel hardware info."

## Config-lever levers (both dead)
- /AmdMtlSettingsFile.txt parser @ driver x+0x10d400 = DEAD CODE (no callers); tested
  (metal-060), no effect.
- Live path is an env-var reader in device-settings init mapping specific env vars to bits
  (AMD_ENABLE_PRIM_BATCH_BINNING -> bit41). No env var exists for enableTexturePipeBankXor
  (bit27) or linearSwizzleTextures (bit36) — searched driver __TEXT strings.

## Remaining kernel avenue (under adversarial-agent evaluation)
Only the TOKEN-TRANSCRIPTION surfinfo (SetupUBMSurfInfoFromTokenSurfInfo /
AccelResource::fillUBMSurfaceInfoInternal) is untested. Viability hinges on whether a
Managed texture's GPU-tiled access AND its CPU-sync copy BOTH derive tiling from that one
kernel _UBM_SURFINFO (so a kernel rewrite of swizzle@+0x230 makes them consistent), or
whether userspace bakes tiling into command buffers/VA independently (kernel rewrite
bypassed => userspace Lilu patch required).

## Lilu-path feasibility note (for the patch fallback)
AMDRadeonX6000MTLDriver is shared-cache-only (no on-disk binary). Lilu UserPatcher's
loadFilesForPatching reads binaryMod->path from disk to LOCATE patterns; if the file is
absent it creates no lookup entry and the patch is silently not applied. So the naive
declarative Lilu patch needs an on-disk copy (extract the dylib from the cache) to locate
the pattern page, then patchSharedCache applies it in-process. WhateverGreen patches
shared-cache CoreDisplay via an on-disk framework path.
