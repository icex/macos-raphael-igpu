# Status

Updated 2026-09-14. This file is **live state only**. Superseded entries are archived in
`findings/research/status-archives/`; the plan is in [docs/ROADMAP.md](docs/ROADMAP.md).

## Current verdict

**The macOS desktop composites on the Raphael iGPU through Metal, and texture copies are
exact.** Two independent GPU boots of candidate 1.0.230 checked **122,548,224 pixels across 96
copy cases with zero mismatches**, plus 2000 offscreen frames and correct window drawables.

Not yet true: a physical display, a diagnosed remote-session artifact, or any game/performance
qualification.

## Current candidate

| Field | Value |
|---|---|
| Version | `1.0.230` |
| Build id | `c115e782494e43f6850aedfb67010375` |
| Executable SHA-256 | `c9e5a856a34ebbe4f3b1bf59de2c613d15edff37c7b2e677a8d476b324bfcf94` |
| Branch | `managed-cow` (merged to `origin/dev`) |
| Worktree | `/home/bogdan/macos-vm/run/worktrees/candidate-230` |
| Card | `metal-078` |
| Boot args | `rgpunobin=1 rgpusdmacfg=2 rgputexdiag=2 rgpugolden=1 rgpuhangdump=1` |

Status: **experimental.** Not merged or pushed to `main`.

## Host state

| Field | Value |
|---|---|
| Host boot id | `c369c74e-96ff-4c21-ae85-80ccb269f7d2` |
| GPU | `0000:7b:00.0`, bound to `vfio-pci` |
| Last recorded launch | **40** (candidate 230 repeat), plus one interactive inspection session on the same boot |
| Last MODE2 reset receipt | `run/mode2-reset-44.json` |
| VM | stopped |

Same-boot relaunch is reboot-free via `tools/smu-mode2-reset.py`. A reset counts as clean only
with `CP_STAT=0` and `RLC_CNTL=0`.

## The three corrections that make it work

| Problem | Cause | Fix |
|---|---|---|
| Graphics ring hangs on the first desktop draw | Navi23-sized DPBB binning (`MAX_ALLOC_COUNT` 340 vs Raphael's 256-line cache) | `rgpunobin=1` |
| Desktop tile-permuted | HWLibs writes `SDMA0_GB_ADDR_CONFIG=0x444`; Raphael is `0x42` | `rgpusdmacfg=2` |
| Managed textures wrong by one pipe-bank-xor bit at 64 px | Apple's userspace Metal driver applies a texture pipeBankXor that mismatches 4 pipes | `rgputexdiag=2` — per-process copy-on-write clear of `enableTexturePipeBankXor` (bit 27) |

The bit-27 patch is delivered entirely in memory from the kext's `AMDAccelDevice::getHardwareInfo`
hook: one private COW byte write, RX restored unconditionally, verified before and after. No
on-disk Apple binary is modified and no security setting is changed.

## Open issues

1. **The bit-27 patch is pinned to build 24G830** — exact driver UUID, `__TEXT` offset `0x13a7e1`
   and instruction bytes. After an OS update it safely **skips**, and the managed-texture defect
   silently returns. Making the locator structural is ROADMAP item 2; a validated read-only
   prototype exists in `findings/research/update-resilience-20260914/`.
2. **8×8 shards over translucent regions — strong evidence it is a lossy remote-desktop
   transport, not a GPU defect (2026-09-14).** The lossless in-guest `screencapture` of the
   desktop is clean where the remote view shows shards (translucent Safari start page, Privacy
   card, menu bar); the shards sit at a 2/5 sub-tile offset over gradients only — a codec
   signature. Seen over both NoMachine and VNC, which are both lossy by default, so both are
   expected. **Not fully closed:** the clean capture is a different frame/resolution than the
   corrupted ones. The confirming test is one artifacted frame grabbed simultaneously via
   forced-raw (lossless) VNC and in-guest capture; if raw-VNC is clean, transport is proven.
   Evidence: `findings/research/desktop-corruption-diagnosed-20260914/`.
3. **The guest has no usable display (2026-09-14).** macOS's own virtual display
   (`VirtDisplay8`, vendor `unkn`, product `virt`) is unstable and eventually stops being
   created; it was never NoMachine's, being recorded hours before NoMachine was installed. Then
   `IOFramebuffer` node count is **0**, `screensharingd` reports `getactivedisplaylist error` /
   `unable to get width and height of display`, and every VNC client (Apple Screen Sharing,
   TigerVNC, RealVNC, and a hand-written RAW client) connects then hangs with no frame. Apple's
   framebuffer carries no DCN 3.1.5, so there is no native scanout to fall back on, and
   suppressing that framebuffer costs Metal outright (see the route (a) section below). A
   watchable desktop now depends on ROADMAP item 3 route (b).
4. **Display output is virtual only.** Apple's framebuffer carries no DCN 3.1.5 code, so there is
   no physical HDMI/DP scanout — ROADMAP item 3.
5. **Root-display presentation mismatch.** The headless root-display capture still differs from
   the window's own capture, even though animated window captures are correct. Do not infer
   physical monitor visibility from the passing tests.
6. **Host-driven clean shutdown is impossible.** macOS ignores ACPI powerdown, so teardown is
   always `{"outcome": "forced"}`. See [docs/host-safety.md](docs/host-safety.md).
7. **Pure kernel-side metadata correction remains unresolved.** The kernel never computes a
   pipeBankXor (no `Addr2ComputePipeBankXor` call sites) and exports none through
   `getIOSurfaceInfo`, so the correction has to happen in userspace.

## Route (a) for a virtual display is closed (2026-09-14)

Candidate **1.0.231** / card **metal-079** tested whether a zero-display-path VBIOS
(`mkrom.py --no-display-paths`) could free the display while keeping Metal. **It cannot.** Apple
created zero `AmdRadeonFramebuffer` instances as intended, but `MTLCreateSystemDefaultDevice()`
then returned nil — "no Metal device" — reproduced twice, even though four `AMDRadeonX6000`
IOService nodes and an `IOAccelerator` were still registered. macOS will not publish a GPU as a
Metal device with no display. The ROM was reverted, framebuffers returned, and Metal device
creation worked again; the live config is back to the proven baseline (connector ROM
`3c6977ee…`, `rgpunobin=1 rgpusdmacfg=2 rgputexdiag=2`). Only route (b), porting DCN 3.1.5,
remains. Detail in [docs/ROADMAP.md](docs/ROADMAP.md) item 3.

## Ledger rules

- A launch is recorded **once VFIO exposure begins**. An abort before QEMU starts is not a launch
  and must not consume a ledger entry.
- Extending a boot's allowance requires an explicit note here naming the boot id and the reason.
- Every launch needs a fresh MODE2 reset receipt immediately before staging, with the host still
  on `vfio-pci` and reachable.
- Authorized runs may last up to 6000 seconds, with manual stop when appropriate; host-fault,
  identity, capture-fatal, shutdown and cleanup abort paths stay armed.

## How to run the next one

```sh
tools/cycle.py --candidate NNN --card metal-0NN --dry-run   # review, no GPU access
tools/cycle.py --candidate NNN --card metal-0NN             # preflight -> reset -> stage -> prepare -> run
```

See [docs/running-an-experiment.md](docs/running-an-experiment.md).

## Boot-launch ledger extension for the raw-VNC confirming test (2026-09-14)

At the user's explicit request ("make sure the qemu is running... run also your own tests"),
candidate 1.0.230 (card `metal-078`, `rgpunobin=1 rgpusdmacfg=2 rgputexdiag=2`) runs as the next
launch on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2` to run the ROADMAP-item-1 confirming test:
capture one artifacted desktop frame over a forced-raw (lossless) VNC path and over a lossy VNC
path from the same live server, plus a RealVNC viewer for the user to watch. `vm-supervision.py
start` with the harness launch options (`GENERIC_GRAPHICS=off`, `BOOTDISK_MODE=custom`,
`NVRAM=stock`, pinned image, `--critical-serial`), `--max-seconds 6000`, after a fresh MODE2 reset
with the host still on `vfio-pci`. Manual stop when the comparison is captured. This note covers
this one launch.
