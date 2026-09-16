# Live status — 2026-09-16, HEVC hardware decode fixed and sustained-tested

## Host and task boundary

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, seven VM exposures completed.
Latest run `c1b774b2087ecdcd4b3edd2d25e788c7` (candidate 277 repeat), MODE2 #142:
CORE_PROBE_PASS, exited-after-guest-request, recovered. No GPU/host fault in
captured kernel messages (network/container messages are present). No QEMU remains;
Raphael `0000:7b:00.0` stays vfio-pci, power/control=on. No further run needed for
this fix; any new exposure requires its own named-boot allowance. No main merge/push.

## Fix and evidence

Candidate **1.0.277**, branch **candidate-277-hevc-service-name**, card metal-124.
14-line driver change renames only the exact marked Raphael PCI node S30 to GFX0
in the IOService plane before hardware-engine initialization. AppleGVA only searches
GFX0/IGPU/IOPP/display names for HEVC capabilities. The previously observed display
node was unrelated IOResources/IOKitRegistryCompatibility/display. The real GPU's
capabilities were correct but excluded by its name. No XPC injection or framebuffer
redesign was needed. Hardware decode now creates codec=4/channel=8/encode=0 contexts.

Same binary SHA256 `1e50cf16c8ac4333a84b84321394cce07b28c94947e1264aa5b86463b588b17a`
passed on two fresh guest boots (same host boot), runs 532ac6d9eefc560e06f6df973245fd67
and c1b774b2087ecdcd4b3edd2d25e788c7. Both shut down by guest request and recovered.

| Workload | Result |
|---|---|
| HEVC HW encode + HW decode, 1080p | 600 frames then 6000 frames on fresh guest; max luma error 1 |
| HEVC SW encode + HW decode | 600 at 720p, 600 at 1080p; zero luma error |
| HEVC HW encode + HW decode after H.264 teardown | 600 at 720p; zero luma error |
| H.264 HW encode + HW decode, 1080p | 600 on each guest; max luma error 1 |

9600 sustained frames total, every frame unique and accounted for, decoder hardware
flag verified, all seven sustained probes exit 0. An additional initial 3-frame
HEVC HW decode passed. Host regression suite: 937 tests, OK (3 skipped).
Exact outputs, identities, SHA256s and independent function/cleanup outcomes:
`findings/research/hevc-decode-qualification-20260916.json`. Analysis and corrections:
`findings/research/hevc-decode-appleGVA-20260916.md`.

## Selection and limits

Use automatic decoder GPU selection with RequireHardwareAcceleratedVideoDecoder.
Explicit RequiredDecoderGPURegistryID remains rejected (-12906): VideoToolbox
classifies this GPU as slotted=0/external=0 and registers global HEVC hardware
decoder without a per-GPU ID. Static registration/filter code explains the result;
it is separate from the fixed capability lookup failure.

Tested Main 8-bit 4:2:0 synthetic luma patterns, sequential sessions, 720p/1080p.
Main10, arbitrary media/chroma fidelity, concurrent sessions and crash recovery
repeatability remain unqualified. Full desktop/display and managed-texture copy
issues unchanged. Handoff client guard remains uninstalled/untested on hardware.

## User remote-desktop run allowance

User explicitly requested starting QEMU for hands-on remote desktop testing.
Extend allowance by one exposure (eighth total) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`: same tested candidate 277 binary, fresh
MODE2, manual-reuse/ack-risk, 6000s maximum and 5400s interactive hold, retaining
all identity, capture-fatal, host-fault, shutdown and recovery paths.
No automated codec workloads beyond the standard baseline probe during this hold.
