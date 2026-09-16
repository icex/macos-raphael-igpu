# HEVC hardware decode fails in AppleGVA capability resolution (2026-09-16)

## Summary

Hardware HEVC **decode** does not reliably work on the Raphael iGPU under macOS.
It fails inside Apple's `VTDecoderXPCService`/`AppleGVA`, above our kext, at the
HEVC decode-capability lookup — before any VCN decode context is created. Hardware
H.264 decode and hardware HEVC/H.264 encode are reliable. The earlier candidate 275
run `5cb7876d` observed one successful HEVC hardware decode; it is not reproducible.

## Evidence

Kext 1.0.275, card metal-122, boot 2508eb6d. Attempts hevc1 (run a6a4215f) and hevc2
(run 0a5f011e), plus the original 5cb7876d.

- Guest unified log, from the decoder XPC service:
  `VTDecoderXPCService (AppleGVA) [HEVC] GVA ERROR: IOGVACodec not set`, then
  `VTDecompressionSessionCreate` returns **-12913** with no GPU registry id, or
  **-12906** (`kVTCouldNotFindVideoDecoderErr`) when the GPU registry id is set.
- The kernel never creates a HEVC decode context: serial shows `VCNCTX video new`
  only for `codec=3` (H.264, channel 8, encode=0) and `codec=7` encode=1 (the HEVC
  *encoder*), never a HEVC decode context. So the rejection is entirely userspace.
- Not a stream-format problem. The software (hevc.vcp) and hardware (hevc.gva)
  streams are both valid Main profile (profile_idc 1), tier high, level_idc 93,
  chroma 4:2:0, 8-bit, 1280x720 (verified by decoding the hvcC and SPS). Both fail
  identically. The earlier "sw stream fails / hw stream works" split was an artifact
  of decode ordering and flakiness, not the bitstream.
- Not decode ordering. hevc2 replayed 5cb7876d's exact order in one clean-boot
  process: H.264 sw-stream -> HW decode PASS, H.264 hw-stream -> HW decode PASS,
  then HEVC hw-stream -> HW decode FAIL (-12913). A prior successful H.264 decode
  does not enable HEVC decode.
- The IORegistry is correct. The PCI GPU node is named `display` (one of the names
  AppleGVA's fallback search recognises: GFX0/IOPP/IGPU/display) and the accelerator
  `AMDRadeonX6000_AMDNavi23GraphicsAccelerator` publishes `IOGVAHEVCDecode = "1"` and
  `IOGVAHEVCDecodeCapabilities` = {VTSupportedProfileArray (1,2,3), VTMaxDecodeLevel
  153}. `IOGVACodec = "AMDVCN2"`. The kext publishes IOGVAHEVCDecode only when
  (MM_EnableHEVCDecode & MM_EnableHEVCEncode)==1, and both hold (HEVC encode works).
  Notably there is **no** IOGVAH264Decode property, yet H.264 decode works — so only
  HEVC decode is gated on this AppleGVA capability lookup.

## Where it fails, in AppleGVA

`FUN_7ffa06717bec` (HEVC decode capability, AMDRadeonVADriver/AppleGVA) has two paths:
- `param_3==0`: iterate IOService, and for a node named GFX0/IOPP/IGPU/display,
  `IORegistryEntrySearchCFProperty(node, IOGVAHEVCDecode, recursive)`.
- else: `FUN_7ffa0670f6d9(metalId)` maps the metalId to a Metal device via
  `MTLCopyAllDevices()` + registryID compare, then searches IOGVAHEVCDecode on it.
Both should find our property. The "IOGVACodec not set" message is emitted when the
recursive property search returns 0. Given the property is present and reachable and
the failure is flaky (worked once), the likely cause is a Metal-device / IORegistry
enumeration or registration inconsistency specific to our grafted, multi-framebuffer
Navi23 topology, resolved inside Apple's closed decoder XPC service.

## Why this is not a quick kext fix

The failure is in a separate sandboxed process (`VTDecoderXPCService`) running Apple's
shared-cache AppleGVA/AMDVA, and it happens before any VCN context, so the kext's
per-process COW patcher (which hooks the video getHWInfo path, as candidate 272 did
for the DPM capability) never runs for the HEVC decoder. There is no register or
queue lever below the driver; the capability is already advertised correctly.

## Concrete next directions (each needs its own bounded run)

1. Instrument `FUN_7ffa0670f6d9`/`FUN_7ffa06717bec` in the decoder XPC process to see
   whether the metalId resolves to our device and which property search returns 0
   (needs patching AppleGVA in VTDecoderXPCService, or DYLD interposing in that XPC
   service via a launchd environment insert — heavier than the kext COW path).
2. Investigate the grafted framebuffer/accelerator topology (the same multi-instance
   issue behind the display work): whether MTLCopyAllDevices sees a consistent single
   Navi23 device with a stable registryID. This ties to the DCN 3.1.5 display work.
3. Compare against a real discrete-AMD Mac's IOGVAHEVCDecodeCapabilities shape in case
   a missing sub-key (e.g. VTMaxPlaybackLevel, per-profile HW-accelerated flag) makes
   VideoToolbox's `FUN_7ff812d2d75a` per-profile check reject our advertisement.
