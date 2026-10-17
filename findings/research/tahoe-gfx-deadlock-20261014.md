# Tahoe desktop freeze: GE parameter-cache oversubscription deadlock (2026-10-14)

## Symptom

On macOS 26.7.1 / 25G241 the desktop froze once particular apps drew 3D content: the
Weather app's VectorKit precipitation map (often opened automatically at login) and the
Memoji/avatar picker during iCloud setup. Apple's driver then logged
`Trying to restart GPU` storms. After a few hundred restarts the VCN engine stayed wedged
for the rest of the host boot (stale `UVD_DPG_PAUSE=4`, decoder ring never advancing), so any
later video decode or hardware encode froze the desktop as well. The handoff's two
"failures" (Weather graphics stall, VCN hardware-encoder stall) are one cause and its
consequence.

## The VCN wait request

The `_wait_for_vcn_response` call that timed out is `HWLibs+0x8e254` on 26.7.1
(`+0x94db1` on 15.8.1): VCN bank 1 register `0x14` (`UVD_DPG_PAUSE`), expected `0x8`, mask
`0x8` (`NJ_PAUSE_DPG_ACK` after the request). It succeeds in every clean run on both
releases. MODE2 and an SMU `PowerDownVcn`/`PowerUpVcn` cycle (candidate 495) do not clear a
wedged VCN; a fresh host boot does. With the graphics deadlock removed there are no restart
storms and VCN decode/encode work (see Verification).

## Reproducer

`run/tahoe-diag-20261014/gfx_bisect.m` renders a 64×64 grid of quads four times per case.
Case `v4,s1,ds,st,inv,kill` hangs: four float4 varyings, Depth32Float_Stencil8, stencil
pass-op Invert, a never-taken `discard_fragment`. One varying passes; MSAA alone, discard
alone, stencil without discard and depth+discard without stencil all pass. Early fragment
tests still hang. The case hangs identically on **15.8.1** with the same driver (candidate
501, matched OS attempt), so this is a latent Raphael fixed-function deadlock that Tahoe's
apps happen to reach, not a Tahoe regression.

Hang state: `CP_STAT=0x94038600`; the ME only polls `CP_COHER_STATUS` for an `ACQUIRE_MEM`
after the draws (`ME_WAITING_ON_REG_READ_DATA`, `SURF_SYNC_NEEDS_IDLE_CNTXS`). SC, PA, BCI,
SPI, SX, DB and CB are busy, and an SQ wave dump (positive control: a spinning shader is
found) shows **zero resident waves**.

## Ruled out

MSAA iteration, GE_PC_CNTL `WAVES_WITH_NO_GRANT` (Navi23 golden 0xA vs Raphael reset 0),
CU masks/harvest/late alloc, Linux GC 10.3.6 golden registers, CAM remap, PA/DB shader
control, the hv_vmm sysctl swap (hangs with `hv_vmm_present=1`), and two groups of global
DB/SC debug bits written by the KMD and verified at the hang (candidate 502: stencil quad
summation/coherency/dual-quad; wave breaks and quad flushes).

## Root cause

Apple's AMDRadeonX6000MTLDriver seeds its GFX10 `AMD_DeviceSettings` with
`allowGePcAllocOverSub` (bit 42, the second default-mask `movabs 0x1ee000000000` in the
device-settings constructor) and emits `GE_PC_ALLOC = OVERSUB_EN | NUM_PC_LINES(511)` with
no VS late allocation, sized for Navi2x. The hanging draw uses Apple's legacy VS pipeline.
Raphael's parameter cache has **256 lines** (Mesa `ac_gpu_info.c`: `pc_lines = 256` for Van
Gogh, Rembrandt and Raphael; Navi21–23 have 1024). Attribute-heavy draws with late Z
(stencil write plus discard) then deadlock the SC/DB/SPI pipeline.

## Fix (candidates 503–506)

The reviewed userspace catalog gains a `ge-pc-oversub` family: the same constructor pattern
as the existing `texture` family, targeting the second default mask, with both immediates
wildcarded so the two patches coexist. The bit index is derived by name from the image's own
Objective-C `AMD_DeviceSettings` layout; there is no OS-build allowlist or fixed offset. The
pattern is unique in 25G241 (`text+0x13a5db`) and 24H32 (`+0x13a82b`). The kext clears the
flag in every Metal client through the existing current-task copy-on-write path when the
process first asks for hardware info. It is on by default; `rgpupcoversub=1` keeps Apple's
setting for A/B tests. `tests/userspace_site_locator.cpp` covers discovery, coexistence,
re-detection and mutation refusal on synthetic and real 26.7.1/15.8.1 images.

Candidate 503 (`rgpunopcoversub=1`): the reproducer and every heavier variant pass, up to
1024×1024 quads at 8× MSAA with 16 varyings plus depth write, including stencil-only and
early fragment tests. Weather runs with zero hang dumps and zero restarts.

## Critical-capture budget

The CR2 critical log has a 512-record lifetime. Each diagnostic category is bounded, but
their sum exceeded 512 once Tahoe apps opened video decode contexts, and the interactive
hold then aborted through the capture-fatal path within minutes. Candidates 504–506 keep
routine records ordinary after the first few: the per-process GEPC lines, VCN context
pairs, SDMA channel remaps, and SUB trace/commit/summary samples (which are not classifier
inputs). Failures stay critical.

## Verification

- Candidate 505 attempt s2 (metal-308): CORE_PROBE_PASS. Weather opened at login with its
  map drawn (3840×2160 ARGB2101010 scanout dump), plus Maps and Chess (SceneKit). The
  reproducer suite passed, with 0 hang dumps and 0 GPU restarts. VideoToolbox `hevc.gva` and
  `h264.gva` hardware encoders each encoded 1200 frames at 1920×1080, with the hardware
  decoder selected, 0 errors and max luma error 1. The guest-requested exit was followed by
  ordinary recovery with `authorizes_launch=true`, and the CR2 log stayed lossless.
- Candidate 506: long soak and desktop-launcher verification. See `status.md`.

## Still open

About one guest boot in four panics or hangs early with kernel code corruption, including
GPU-less compatibility-refresh guests (invalid opcode in APFS, strcmp GPF, vtable faults).
Host logs showed no MCE, EDAC or bad-page errors. The earlier lost-IPI interpretation
was a hypothesis: later evidence captured APFS integrity failures before a pmap panic,
with parked CPUs afterward. An explicitly verified single-vCPU guest also panicked.
Plugin-disabled trials retain integrity failures. See the
[2026-10-15 investigation](guest-memory-corruption-20261015.md) for exact artifacts,
configuration checks and limits; kernel-update timing alone does not identify the cause.
The latest continuation found AMD display IH records in host cached-file corruption and
the earlier TCG core, with the unowned iGPU's IH0 DMA still active after QEMU exit.
Bounded IH containment stopped it; permanent teardown/recovery coverage remains open.
