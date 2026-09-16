# Live status — 2026-09-16, HEVC hardware decode fixed and sustained-tested

## Host and task boundary

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`: capturepath run
`b92d134b7f4cfde7658852b446d594db` stopped by guest-request and recovered
(shutdown.json and recovery.json, CP_STAT=0). GPU remains vfio-pci, power/control=on.
Green/purple transparency corruption remains unresolved. Native animated colored
NSVisualEffectView backdrop reproduces it; gray-only probes were insufficient.
Desktop GPU trace is complete; colored-backdrop trace is partial (metadata missing).
Detailed evidence and probes are in candidate278; its driver change is rejected.

## Color interpolation follow-up allowance

Standing user instruction to fix and continuously test authorizes one additional
exposure (eleventh) on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, attempt colorrepro,
using unchanged candidate277/card metal-124 with fresh MODE2, maximum6000 seconds,
5400-second hold and all identity/capture-fatal/host-fault/shutdown/recovery aborts.
Hypothesis: nonconstant half-precision interpolants fail; smallest discriminator
is CPU-verified varying-color gradient, followed by controlled native reproduction.
No direct OpenGL workload. Earlier successful probes do not qualify the desktop.

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
repeatability remain unqualified. Full desktop/display remains unqualified; candidate230’s managed-texture
copy fix remains in place. Handoff client guard remains uninstalled/untested on hardware.

## User remote-desktop run allowance

User explicitly requested starting QEMU for hands-on remote desktop testing.
Extend allowance by one exposure (eighth total) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`: same tested candidate 277 binary, fresh
MODE2, manual-reuse/ack-risk, 6000s maximum and 5400s interactive hold, retaining
all identity, capture-fatal, host-fault, shutdown and recovery paths.
No automated codec workloads beyond the standard baseline probe during this hold.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-277-attempt-userdesktop-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

## Capture-path follow-up allowance

User’s standing fix-and-test instruction covers one additional exposure (tenth)
on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`: known candidate277, isolated attempt
capturepath, card metal-124, fresh clean MODE2, 6000s maximum, all safety aborts.
Candidate278’s linear layout did not fix corruption and its direct OpenGL render
probe hung the guest; guest-request shutdown and recovery both completed.
Revert to 277 for tracing ScreensharingAgent capture and its native fallback paths.
Do not rerun the hanging OpenGL workload. Preserve the working Metal/codec stack.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-277-attempt-capturepath-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
