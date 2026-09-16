# Live status — 2026-09-16, HEVC decode investigated

## Current host and task boundary

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, Raphael `0000:7b:00.0` on **vfio-pci**,
`power/control=on`, no QEMU. Four VM exposures this boot (275 run 5cb7876d, then
attempts hevc1/hevc2 for the decode investigation, plus the earlier 274). All ended
`exited-after-guest-request` with a `recovered` receipt and no kernel messages. A new
run needs a fresh allowance note naming this boot, MODE2 reset (next #138) and
`--manual-reuse --ack-risk`. No vfio-pci -> amdgpu rebinding within a boot. Nothing
merged or pushed to main.

## Codec status (kext 1.0.275, card metal-122, branch candidate-275-vcn-wptr)

Reliable, hardware-confirmed (run 5cb7876d and reproduced across attempts):

| Path | Result |
|---|---|
| H.264 hardware **decode** (sw- and hw-encoded streams) | 3/3 frames, max luma error 1 |
| H.264 hardware **encode** (h264.gva) | 3/3, encodes and round-trips |
| HEVC hardware **encode** (hevc.gva) | 3/3, encodes and round-trips |

Fix that made these work: 273/275 raw decoder write pointer (drop Apple's DPG-only
bit31 in the shared/SCRATCH2 write pointer) on top of 272's AMDVA no-DPM capability
correction and 274's diagnostic removal. See
`findings/research/vcn-raw-wptr-20260916.md`.

Not reliable:

| Path | Result |
|---|---|
| HEVC hardware **decode** | Fails in AppleGVA userspace ("IOGVACodec not set", -12913; -12906 with a GPU registry id). Observed working once (5cb7876d); not reproducible in 4 later attempts on 2 clean boots. |

## HEVC decode root cause (this session)

The failure is inside Apple's `VTDecoderXPCService`/`AppleGVA`, above our kext, at the
HEVC decode-capability lookup, before any VCN decode context (the kernel never sees a
HEVC decode `VCNCTX`). It is **not** a stream-format problem: the software (hevc.vcp)
and hardware (hevc.gva) streams are both valid Main-profile 8-bit 4:2:0 (hvcC/SPS
decoded and checked), and both fail identically. It is **not** decode ordering: a
clean-boot replay of 5cb7876d's exact order (H.264 sw+hw decodes, then HEVC decode)
still fails. The kext correctly publishes `IOGVAHEVCDecode="1"` with valid
`IOGVAHEVCDecodeCapabilities` on the accelerator under a PCI node named `display`.
H.264 decode has no such IORegistry gate, which is why it is unaffected. Full analysis
and next directions in `findings/research/hevc-decode-appleGVA-20260916.md`. This is
not fixable with a bounded kext change; it needs work inside Apple's decoder XPC
process or on the grafted framebuffer/accelerator topology (shared with the display
work). The earlier status claim that HEVC hardware decode "works 3/3" is corrected:
that single result is not reproducible.

## Other open issues

1. Only three-frame codec workloads are qualified. Sustained streams, other
   resolutions, HEVC Main10, alpha, and concurrent sessions are untested.
2. Full desktop/display path (DCN 3.1.5) unqualified; managed-texture copy
   limitation unchanged.
3. GPU handoff client guard (`fix/gpu-handoff-clients`): fixture-tested, not installed
   into `~/macos-vm/` copies or the `experiment.py` harness list, not hardware-tested.

## Suggested continuation

1. HEVC decode: instrument AppleGVA's capability resolver in the decoder XPC process
   (DYLD interpose in VTDecoderXPCService), or clean up the accelerator topology so
   `MTLCopyAllDevices` returns one stable Navi23 device. Both are larger efforts.
2. Sustained H.264/HEVC encode + H.264 decode qualification (e.g. 600 frames like the
   Linux baseline), then consider merging the 275 kext changes toward `dev`.
3. Finish the handoff guard before the next reboot-based Linux control.

Previous state archived in
`findings/research/status-archives/status-before-hevc-decode-20260916.md`.
