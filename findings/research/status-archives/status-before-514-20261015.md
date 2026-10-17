# Live status — 2026-10-14 — release 509: smooth 120 Hz window drags

Host boot 935ccd73-6305-448d-a1c0-e14002a13a21, LTS kernel 6.18.55-2-cachyos-lts (memtest
passed), BIOS UMA frame buffer 4 GB. The desktop launcher is release 509 / metal-313 with QEMU
pins v16 (worktree candidate-509); the user's session `d20261014203249` is running. Release 506
and 490 worktrees stay for rollback (run/release.conf.before-507-20261014 holds the 506 config).

## Delivered today (releases 507–509)

- **Window drags reach QEMU's window at 120 Hz (509).** The SDMA scanout copier treated a
  frame as new only when its address differed from the last copied one, so macOS's rotating
  buffers made it wait for the 100 ms refresh: 9 fps in QEMU's window while Metal presented
  120.0. It now samples every flip. Window stress: 119.9 fps in QEMU's window, matching macOS
  (p99 8.4 ms), with one and three windows.
- **Apple's reusable-allocation cache is capped (508).** `IOAccelOrphanedMemoryPool::init` is
  given `hw.memsize / 4` (3.67 GB); the kext clamps it to min(512 MB, VRAM/4) through the
  exported symbol. A 10-minute stress stayed at about 1.7 GB cached, 1.5 GB free, 0 failures.
- **Clipboard on the iGPU display, QEMU USB menu (507).** The guest agent sends one capability
  announcement (QEMU's vdagent closed the port on a second) and runs without the console
  bridge; pins v16 restore Machine › USB Devices…; the shortcut has **USB devices…**.
- The desktop Metal probe compiles with Xcode 26.5's clang (explicit `CGBitmapInfo` casts).
- New tools: `tools/rgpu-top.sh`, `tools/rgpu-window-test.sh` + `rgpu-window-stress.m`,
  `tools/rgpu-display-mode.m`.

Benchmark on 507 (4 GB UMA, idle desktop): 2818–2822 GPU render fps and 282–284 GFLOP/s,
matching the 490 baseline. Evidence:
[findings/research/desktop-smoothness-20261014.md](findings/research/desktop-smoothness-20261014.md).

## Runs today (2–3 line briefs)

- **506 `d20261014162629`:** first boot on the LTS kernel; Xcode 26.5 and the iOS 26.5
  simulator installed and working; clipboard fixed live. Capture: no panic, 0 GPU restarts.
  Guest-requested exit; ordinary recovery recovered, authorizes=true.
- **507 `d20261014191256` / `…191546`:** the first start stopped before GPU exposure (Xcode
  clang rejected the probe; a GPU-less guest was left running and was sealed by a manual
  refresh). The second ran: VRAM 4096 MB, clipboard both ways, QEMU USB menu, benchmark.
  Window stress baseline: 33.8 fps in QEMU's window, 698 allocation failures, 235 ms stalls.
  Guest-requested exit; ordinary recovery recovered, authorizes=true.
- **508 `d20261014194209`:** guest kernel panic in `nd6_sched_timeout` before any GPU work
  (the open guest-corruption issue, now seen on the LTS kernel). Cancelled; ordinary recovery
  failed as expected, noqueue recovery recovered, authorizes=true.
- **508 `d20261014195109`:** clamp logged `0xdac00000 -> 0x20000000`; 0 allocation failures and
  no stalls in repeated stress; QEMU-window fps still low (found the copier bug). Guest-requested
  exit; ordinary recovery recovered, authorizes=true.
- **509 `d20261014203249` (running):** 119.9 fps in QEMU's window with 1 and 3 windows; user:
  "windows are super smooth now". Shutdown and recovery pending (the user's session).

## Open

- **VRAM cache in longer real use.** After about 40 minutes of the user's session (Photos,
  Safari, Mail) the cache held 3.18 GB, 14 MB free, and allocations failed again (350 in a
  20-second drag test, worst frame 66 ms). Pruning frees an allocation only when
  `IOAccelMemoryMap::testEvent` reports its GPU event complete; some never do. Next: find
  those events (channel/stamp) or evict on allocation failure.
- **Audio dropouts** while dragging windows over Safari playing YouTube (user report). Leads:
  QEMU now copies 120 4K frames per second, its process runs at nice 9 and the PulseAudio
  backend uses default buffering; or VRAM allocation failures stalling WebKit's media path.
- **Guest kernel corruption:** early panics continue on the LTS kernel (1 of about 9 boots on
  2026-10-14 evening; memtest passed). Cancel with SIGTERM to `experiment.py`; the launcher
  then runs the noqueue recovery.
- The guest still uses a temporary LaunchAgent (`org.raphaelgpu.clipboard`) until the console
  support package is reinstalled with the new `start-console.sh`.
- Scaled-mode QEMU freeze (logical 2048×1152) remains open.

Previous status: [status-archives/status-before-desktop-509-20261014.md](findings/research/status-archives/status-before-desktop-509-20261014.md).
