> Superseded investigation diary. Some interpretations below are explicitly corrected
> by guest-memory-corruption-20261015.md and the current status.

# Live status — 2026-10-15 — release 514: VRAM stays free, aspect-locked window

Host boot ee006810-2a60-4378-b4de-8d673b8c3f00, kernel 7.2.10-1-cachyos-bore, BIOS UMA frame
buffer 4 GB. The desktop launcher is release 514 / metal-318 with QEMU pins v18 (worktree
candidate-514); no VM is running (the last session ended at 00:48 with ordinary recovery,
authorizes=true). Rollback configs:
run/release.conf.before-507-20261014 (506) and run/release.conf.before-506-20261014 (490).
The user keeps the host configuration unchanged (no ananicy rule, no kvm_amd changes).
Handoff for the remaining issues: [docs/handoff-remaining-issues-20261015.md](docs/handoff-remaining-issues-20261015.md).

## Delivered (releases 510–514)

- **VRAM cache released under pressure (511/512).** The accelerator's second, unlimited orphan
  pool holds freed VRAM and is emptied only by the sleep path; it reached 3.2 GB in real use.
  The kext calls the pool's exported `releaseOrphanedMemory` inside `addMemory` (before Apple's
  add, after a 511 use-after-free found by security review) after an allocation failure or every
  30 s. Stress: cache ~350 MB, 2.5 GB free, 0 failures. `rgpuvidorphan=0` disables it.
- **QEMU window aspect (510).** Pins v17+ snap the window to the display's aspect 150 ms after a
  resize, following the dragged edge. KWin-scripted tests and the user confirm it.
- **Audio path (510/513).** usb-audio buffer 256 ms, PulseAudio latency 80 ms, 48 kHz output, and
  QEMU image c513 accepts variable USB audio packet sizes. These did not fix the dropout below.
- **Diagnostics.** `rgpuevdiag=1` (testEvent failures per channel), 514's `rgpusdmamaxfps` copy
  cap and SDMACOPY poller statistics; `install-desktop.sh` now deploys `tools/vm-entry.sh`.

## Runs (2–3 line briefs)

- **510 `d20261014214128`:** guest panicked at boot (`mount[4] exited`); cancelled, ordinary
  recovery failed as expected, noqueue recovery recovered. Recovery First Aid then found the disk
  clean (backup: ~/macos-vm/backups/mac_hdd_ng-26.7.1-20261014-2135.qcow2).
- **510 `d20261014220845`, 511 `d20261014221952`, 512 `d20261014222944`/`d20261014225831`,
  513 `d20261014230844`:** Metal probe 24/24, VRAM release active, aspect snap active, audio
  tests. Capture: no GPU restarts or panics. Each ended guest-requested with ordinary recovery
  recovered, authorizes=true.
- **508 A/B `d20261014235447`:** audio clean, but the guest presented almost no frames (display
  5120×2880@60 with the user's monitor off), so the comparison is not valid. Ordinary recovery.
- **514 `d20261015000754`:** two GPU-less refresh failures before a seal; the GPU boot reached
  the desktop; poller ~17 µs per tick; aspect snap tested via KWin. Ended 00:48 with ordinary
  recovery recovered, authorizes=true.

## Open

- **Audio silence under ~120 fps compositing.** Guest sends ~1042 USB isochronous packets per
  second filled with silence; QEMU, PipeWire and the USB path are clean; offscreen GPU load is
  fine. Needs the user's monitor on (4K@120). Next: A/B metal-318 vs metal-319 (30 fps cap).
- **Guest boot corruption.** Started right after the 2026-10-12 host kernel update (7.2.5 →
  7.2.9 and LTS 6.18.50 → 6.18.55); 6.18.55 and 7.2.10 still fail GPU-less boots (often 1–3
  tries). Recovery First Aid found the APFS container and all volumes clean; THP off and 4 vCPUs
  did not help. The launcher's retry and noqueue recovery cope.
- Scaled-mode QEMU freeze (logical 2048×1152) remains open.

Evidence: [findings/research/desktop-smoothness-20261014.md](findings/research/desktop-smoothness-20261014.md).
Previous status: [status-archives/status-before-514-20261015.md](findings/research/status-archives/status-before-514-20261015.md).

## Memory investigation — 2026-10-15

Priority: guest boot corruption before audio (user). Worktree candidate-515 from remote dev
319a2dd (hosted test/build passed). Host configuration unchanged; iGPU remains vfio-pci,
power/control=on. Stopped disk reflink backup: backups/mac_hdd_ng-before-memory-diag-20261015.qcow2.

- GPU-less baseline-01: macOS 26.7.1 reached userspace, compatibility capture sealed after
  acknowledged native shutdown (exit 0). Serial capture attached after startup; retained
  register sample/RAM dump are from a running guest and do not show a crash. Evidence:
  ~/macos-vm/run/memory-diag-20261015/baseline-01-*. No GPU exposure/recovery needed.
- Earlier refresh failures at d20261015000012 and d20261015000517 must not be counted as
  boot failures without checking: the first already uploaded successful RGPU_COMPAT output
  before timing out waiting for native shutdown. Boot, capture and shutdown are separate.

Next: finite XNU TLB-flush timeout to obtain the first failure, then per-VM interrupt/CPU A/B.
Baseline host suite: 1637 passed, 8 skipped.

- GPU-less baseline-02: reached userspace but two system daemons crashed with general
  protection faults (both report guest CPU 6); compatibility capture failed its unchanged
  live-vs-uploaded image SHA gate. Retained serial, IPS reports, container identity,
  registers and 2 GiB RAM dump under memory-diag-20261015/baseline-02-*. Stopped the
  frozen GPU-less container after evidence capture (forced; no clean shutdown claimed).
  No VFIO exposure. This reproduces corruption symptoms without an accelerator.

- GPU-less finite-tlb-01: compatibility capture and native exit succeeded. The nominal
  10,000,000 us argument was not a 10 s timeout: live `_TLBTimeOut` readback was
  0xa817c80000 ns (~722 s), matching XNU's uint32 truncation then `vti=9` inflation.
  It provides no short-timeout diagnostic conclusion. Next uses 19,531 us * 512 (~10 s).

- GPU-less finite-tlb-02: live `_TLBTimeOut` confirmed 9,999,872,000 ns (~10 s).
  APFS reported a compressed-data hash mismatch at inode 10819 / offset 39550976,
  then the first panic at uptime 39.64 s was `pmap_pv_remove: null pv_list` in
  mDNSResponderHelper, CPU 0. Subsequent nested debugger faults and seven parked
  CPUs are later effects, not evidence of an initial lost IPI. Serial + first-panic
  RAM retained under memory-diag-20261015/finite-tlb-02-*. No GPU exposure.
  Capture did not seal; failed GPU-less guest force-stopped after evidence capture.

The 2026-10-12 amd-ucode package upgrade was also audited: the family-1Ah firmware
blob is byte-identical in cached 20260810, 20260910 and 20260916 packages, including
the running patch 0x0b404035. This package change did not change this CPU's firmware.

- GPU-less no-rgpu-01 (`-rgpuoff`, same finite TLB timeout): plugin initialization
  absent from serial; compatibility images checked and native shutdown/seal succeeded
  (89 s). This single pass does not establish causality. Next repeats with a synchronized
  file-remap canary. Evidence: memory-diag-20261015/no-rgpu-01-*.

- GPU-less no-rgpu-02-canary: RaphaelGPU initialization absent, but APFS still logged
  a compressed-data hash mismatch (different inode 10811, offset 385777664), before
  the canary started. Disabling the plugin therefore does not remove this integrity
  failure. Canary/images/native shutdown results are recorded separately below.
  Next changes only this VM's interrupt controller (`kernel-irqchip=off`), keeping
  plugin-off and the measured ~10 s TLB timeout. No host module change.

  no-rgpu-02-canary completed 47,934 remaps / 98,168,832 page checks with zero canary
  mismatches, valid image SHAs and native shutdown/seal. Those passes do not erase
  its earlier APFS integrity failure.

- no-irqchip-01 launch refused before macOS: QEMU/KVM reports `KVM does not support
  userspace APIC`. No corruption or AVIC verdict follows. No GPU exposure. Journal
  retained. QEMU's unpinned automatic RAM was 14 GB in baseline-02 and 15 GB in
  finite-tlb/no-rgpu trials; pin subsequent comparisons explicitly rather than treating
  it as a constant. Plugin-off APFS failure still excludes plugin necessity, independent
  of that size difference.

- no-irqchip-02: masking x2APIC did not change the pre-boot refusal. Source confirms
  QEMU 10.1.2 rejects KVM userspace APIC unconditionally; this path cannot test AVIC.
  No guest ran and no GPU exposure occurred. Next: pinned 15 GB, eight actual vCPUs (intended one-vCPU override was not forwarded), plugin-off,
  measured finite TLB timeout; standard in-kernel interrupt controller.

- one-cpu-01 (15 GB, `-rgpuoff` (CPU-count override not forwarded)): system-process crash storm then
  `Taking non-sleepable RW lock with preemption enabled` in APFS getattr for
  NotificationCenter. First panic retained, guest force-stopped after capture.
  The intended single-vCPU experiment did not run; cross-vCPU shootdowns remain untested. XNU __TEXT snapshot
  has the same 234 changed bytes / eight patched symbol locations as the prior live
  snapshot (outside header), with no additional differing locations. This does not
  prove every kext or data mapping correct. No GPU exposure.

- thp-off-01 was also an invalid A/B: image override was not forwarded and its initial
  image build had failed. Actual original-image / 8-vCPU control logged APFS integrity
  failures and failed the image SHA gate again; no THP-off conclusion follows.
  The diagnostic launcher now forwards only IMAGE/RAM_GB/VCPUS explicitly and writes
  expected-vs-observed configuration evidence before counting trials.

- one-cpu-02: expected/observed config and QEMU argv verify **one** vCPU / 15 GB /
  original pinned image. First panic at ~2.5 min: `kernel stack overflow`, reporting
  inconsistent stack base/top and depth 0x4321cd70. First-panic serial, XNU text,
  registers and RAM retained; guest force-stopped after capture. A failure now is
  independently observed without cross-vCPU guest shootdowns; the earlier mislabeled
  one-cpu-01 result remains excluded from that conclusion. No GPU exposure.

- thp-off-02 never booted: relocated QEMU could not find firmware ROMs. No guest verdict.
  thp-off-03 uses explicit firmware path and the original QEMU binary SHA unchanged;
  expected/actual image/15 GB/8 vCPUs/AHCI match. Live process THP_enabled=0, 0 anonymous
  huge pages, still THP=0 at 7+ GB RSS. Boot, 47,541 canary remaps / 97,363,968 page
  checks, four image SHAs and native exit/seal passed; no APFS hash errors or panic.
  One clean trial is not a fix verdict; repeating the exact configuration.

- thp-off-04: same verified configuration, live THP=0 at ~12 GB RSS, but APFS
  rejected a dyld shared-cache page (inode 10813 / offset 99876864). THP disable
  is insufficient. Next discriminator: same fixed 15 GB / eight vCPUs / plugin-off
  configuration with the system disk on emulated NVMe instead of AHCI.

  thp-off-04 nevertheless passed its later canary, image checks and native shutdown;
  its APFS integrity error makes the overall memory result a failure. No GPU exposure.

- nvme-01: expected/actual settings and argv verify NVMe / 15 GB / eight vCPUs /
  THP=0. Boot, canary, image SHAs and native shutdown/seal passed; no APFS hash
  errors or panic. One pass is not a controller-fix verdict; repeating exactly.

- nvme-02: verified NVMe / same THP-off image / 15 GB / eight vCPUs, but first
  panic was again `pmap_pv_remove: null pv_list`, CPU 4. NVMe is not sufficient.
  First panic, registers, XNU text and RAM retained; failed guest force-stopped.
  No GPU exposure. Next disables Lilu explicitly: plugin-off did not disable its
  kernel-trap and OSKext hooks, visible in the XNU text comparisons.

- no-lilu-01: explicit disabling message, live snapshot restores original bytes at
  kernel_trap and two OSKext hooks (the bootstrap patch remains). VirtualSMC uses
  legacy gen1 mode; this is a bundled framework/SMC change, not isolation of one hook.
  Boot, canary, image checks and native exit passed without APFS hash errors or panic.
  Repeating before attributing the fault to Lilu.

- no-lilu-02: same verified configuration and explicit Lilu disable, but APFS
  rejected another dyld-cache page (inode 10813 / offset 191397888). Later canary,
  image checks and native exit passed. Lilu disable is insufficient.
  Next compares a reflink clone of retained macOS 15.8.1, in its own VM directory;
  original rollback disk and active Tahoe disk preserved.

- sequoia-01: isolated reflink clone booted macOS 15.8.1 / 24H32 under the same
  verified 15 GB / eight-vCPU / NVMe / THP-off / Lilu-off setup. Canary passed
  104,108,032 page checks, but compatibility image SHA validation failed. Thus the
  observed data disagreement is not confined to Tahoe. Failed clone guest force-stopped;
  original rollback disk preserved. Production config.plist, OpenCore.qcow2 and oc-raw.img
  now restored byte-for-byte (production-configuration-restored.json). No GPU exposure.

- apic-kernel-control-01: isolated diagnostic QEMU / same Sequoia clone / 15 GB /
  eight vCPUs / NVMe / THP=0 / Lilu-off, normal kernel APIC. QOM and `info kvm`
  verify kvm-apic and KVM enabled. Guest panicked (CPU 2 page fault); first-panic
  capture retained, failed clone force-stopped.
- apic-userspace-01: same binary with `kernel-irqchip=off` selected the deprecated
  userspace APIC, but emitted no BIOS serial and the monitor did not answer. Stopped
  by exact container ID, permits revoked, collector terminated only after the guest
  container stopped. No macOS result and no AVIC conclusion. This image is diagnostic
  only and is not installed. Next pins the same standard-APIC clone at 8 GB, recording
  per-process RSS/swap/THP. Host configuration remains unchanged.

- ram8-01: verified 8 GB / eight vCPUs / normal kernel APIC / NVMe / Lilu-off /
  THP-off, same Sequoia clone. APFS reported two different bad hashes for the same
  compressed stream/offset; then `Using inactive port` panic in familycircled.
  Maximum sampled QEMU VmSwap was 0 kB (RSS ~7.7 GiB). This failure does not require
  15 GB or observed swapping of the guest process. First-panic capture retained,
  failed clone force-stopped.
  Next runs this disposable clone with TCG solely as a KVM discriminator, not a
  desktop solution; bounded 900 s collector / unchanged 6000 s service deadline.
