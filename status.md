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
3. **Display output is virtual only.** Apple's framebuffer carries no DCN 3.1.5 code, so there is
   no physical HDMI/DP scanout — ROADMAP item 3.
4. **Root-display presentation mismatch.** The headless root-display capture still differs from
   the window's own capture, even though animated window captures are correct. Do not infer
   physical monitor visibility from the passing tests.
5. **Host-driven clean shutdown is impossible.** macOS ignores ACPI powerdown, so teardown is
   always `{"outcome": "forced"}`. See [docs/host-safety.md](docs/host-safety.md).
6. **Pure kernel-side metadata correction remains unresolved.** The kernel never computes a
   pipeBankXor (no `Addr2ComputePipeBankXor` call sites) and exports none through
   `getIOSurfaceInfo`, so the correction has to happen in userspace.

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
