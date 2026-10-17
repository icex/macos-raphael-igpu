# Handoff: remaining desktop issues (2026-10-15, after release 519)

Read `AGENTS.md`, `status.md` and `docs/host-safety.md` first. The rules there apply: work in a
candidate worktree under `~/macos-vm/run/worktrees/`, never in `~/src`; run hardware through the
launcher or `tools/cycle.py`; keep the host suite green (`python3 -B -m unittest discover -s tests`);
update `status.md` after each hardware run; push `dev` only after hardware verification and wait
for hosted CI; never publish `main` unless asked. The user does **not** want host configuration
changed (no ananicy rule, no `kvm_amd` parameters, no kernel downgrade by us); never handle Apple
account credentials.

## Investigation update (2026-10-15, release 515)

The unowned iGPU's IH0 DMA kept writing after QEMU exit, and AMD display IH
records were found in host corruption, the old TCG core and a Tahoe cache.
Release 515's independent guard holds the VFIO descriptor outside QEMU,
stops IH/display/GC/SDMA before guest RAM unmaps, and records five stopped
samples. Two native and two exact QEMU/container PID1 death runs passed that
boundary. Ordinary recovery is incomplete after the guard halts active HQDs;
the supervised MODE2/no-queue path issued separate authorizing receipts. Two
post-crash Tahoe boots passed bounded remap/pmap stress, four image hashes and
native exit. The corrupt symbolication cache was quarantined after clone
validation and a stopped-disk backup. The earlier `heap` pmap panic's exact
cause remains unknown; these observations have bounded coverage. No GPU
binding or host KVM setting was changed. See [current status](../status.md).

The [independent audit](../findings/research/guest-memory-corruption-20261015.md)
reproduces APFS integrity failures with RaphaelGPU disabled and with Lilu disabled,
a verified single-vCPU panic, and image disagreement in an isolated macOS 15 clone.
THP-off and NVMe repeats also failed. Kernel-update timing and parked CPUs do not
identify the cause. Some old refresh failures occurred after successful collection,
during shutdown. The active desktop configuration is release 519 after the
installed shortcut passed Metal, a readable desktop and native stop/recovery.

The old statement that USB packets contained silence was an inference: QEMU
counters measured lengths/drops, not amplitudes. Hosted test/build CI passed
for the memory milestone at `ce5bfe8`. Automated release-515 tone and foreground
player tests passed, but a slow manual QEMU-window resize reproduced a
guest-wide audio halt. Safari/YouTube stuttered during fast page scrolling;
the same page did not stutter in Safari Picture in Picture or Brave. The user
classified both audio issues as lower priority. See
[audio evidence](../findings/research/audio-dropout-20261015.md).

## Where things stand

- The desktop launcher (`~/.local/bin/raphael-macos`, config
  `~/.config/raphael-macos/release.conf`) runs release 519 / card metal-324 / QEMU pins v20 from
  worktree `candidate-519`. Guest: macOS 26.7.1 (25G241), 14 GB RAM, 8 vCPUs, BIOS UMA 4 GB.
  Since October 17, the installed launcher and `desktop-inhibitor.py` own the
  inhibitor container/logind blocker through startup and recovery, then release
  them. Keep `rgpu-inhibit` stopped between sessions with `restart=no`; do not
  start a persistent development sleep blocker for ordinary shortcut use.
  The card now has `startup_workload=none`: no automatic Metal probe or test
  windows. A serial-specific uaccess rule permits the attached Intel SSD's
  ASMedia `174c:1153` enclosure through the existing USB picker.
- Working: Metal desktop at 4K/5K HiDPI 120 Hz with every flip copied to QEMU's window (509),
  VRAM cache released under pressure (512), clipboard and QEMU USB menu (507), aspect-locked
  QEMU window (510), guest-mode window fit capped to the host work area and
  visible pointer (v20, user-confirmed), validated scaled 4096×2304/120
  copying (519), Xcode 26.5 and iOS Simulator in the guest.
- Evidence: `findings/research/desktop-smoothness-20261014.md`,
  `findings/research/tahoe-gfx-deadlock-20261014.md`.

## Guest corruption: repaired measured teardown boundary, residual uncertainty

**Confirmed.** GPU-less Tahoe trials produced APFS compressed-data hash errors,
image SHA disagreements and unrelated first-panic signatures. One BootKC upload differed
from a good copy in exactly four bytes at a 4 KiB page boundary. The guest-reported hash
still matched the good copy. No accelerator was attached.

**Controls.** RaphaelGPU-off and Lilu-off repeats retained integrity failures. A verified
one-vCPU guest panicked with an inconsistent kernel stack. Verified THP-off and NVMe
repeats failed. A reflinked macOS 15.8.1 clone also had guest/uploaded SystemKC disagreement;
its 8 GB repeat panicked with QEMU VmSwap=0 throughout the sampled interval. Earlier
`one-cpu-01` and `thp-off-01` labels had unapplied environment overrides; they are explicitly
retracted as those controls in the audit. Use the observed configuration artifacts.

**Interpretation.** `tlbto_us=0` suppresses the timeout panic but still waits for TLB-flush
acknowledgements. A verified finite ~10 s timeout captured APFS corruption before a pmap
panic; parked CPUs came later. The first fault is not demonstrated to be a lost IPI.
A synchronized mmap canary can pass despite these other failures and is not qualification.

**Historical discriminator.** Both software-emulation trials are finished: eight-vCPU TCG segfaulted in
QEMU; one-vCPU TCG hit its 6000-second deadline at 00:40:23 UTC without a command
response. Neither provides a clean KVM comparison. Direct upstream KVM memory-slot
and MMU controls passed, with narrow coverage. A fresh GPU-less macOS 15 control
reproduced SystemKC disagreement while PCIDE was clear on all eight CPUs, with
no second NIC, TAP or DRI device. The planned PCID-off intervention was therefore
cancelled. An instrumented repeat caught a correct guest buffer before/after sending,
but a bad received file; that file's cached host contents then kept changing after
guest exit, while O_DIRECT/reflink reads matched its original received SHA. Structured
overwrites match AMD IH client 4 / source 0x57 (OTG0 VUPDATE_NO_LOCK), also seen in
the TCG core. Read-only iGPU IH0 sampling found ring DMA, interrupts and writeback
enabled at ~120 entries/s; ring base 0x11f6e000, writeback 0x11cf0000. Those enables
were cleared under the experiment lock and the pointer stopped. Two fresh GPU-less
clones then passed canary/image checks and acknowledged native shutdown with exit 0;
the host cached artifact stayed stable for 120 seconds. The guarded release and
crash/recovery repeats described above supersede the earlier proposed teardown work.
See the audit and
`memory-diag-20261015/continuation-01/`.
Host AVIC/NPT or kernel changes still require explicit user instruction. Do not retry GPU
runs to diagnose this CPU-only failure. The installed disk was retained, with a stopped-disk
backup before quarantining the corrupted cache. Disk backup and raw evidence:
`~/macos-vm/backups/mac_hdd_ng-before-memory-diag-20261015.qcow2` and
`~/macos-vm/run/memory-diag-20261015/`.

## Audio: two reproduced symptoms, now lower priority

**Current symptoms.** Slow manual QEMU host-window edge drags can halt all
guest audio for about two seconds. Fast scrolling a Safari YouTube page can
stutter that video's audio while an independent guest tone and USB packet
stream continue. Picture in Picture and Brave played the same page without
reported stutter. The user marked these audio issues lower priority. Earlier
automated QEMU resize requests took effect almost instantly and did not
reproduce the slow-drag failure.

**Objective reproducer** (no listening needed):
1. Guest: a 440 Hz WAV at `/var/tmp/rgpu-tone.wav` (90 s, 48 kHz stereo); play with
   `afplay` over SSH (`run/tahoe-diag-20261014/guest.sh`, key `~/macos-vm/vmkey`, port 50922).
2. Host: record the output device monitor —
   `pw-record -P '{ stream.capture.sink=true }' --target alsa_output.pci-0000_03_00.1.pro-output-7 --rate 48000 --channels 2 --format s16 out.wav`
   (recording QEMU's stream node directly yields near-silence).
3. Load: `tools/rgpu-window-test.sh 20 3 LABEL` (three moving/resizing windows plus a Metal
   present probe; prints QEMU-window fps and macOS presented fps).
4. Analyse 1 ms RMS: silence = RMS below 30 % of the steady tone level.

**Earlier measurement (513/514).** Idle: 0 gaps. 20 s offscreen GPU benchmark (`/var/tmp/rgpu-bench/bench`): 0 gaps.
Window stress at 3840×2160@120 (QEMU window 104 fps, macOS presenting 107 fps): 22 of 30 s
silent, bursts at each 2 s window resize. During the silence QEMU's main thread was 2.8 % busy,
PipeWire `ERR` stayed 0, `coreaudiod` logged no overloads, a QEMU xHCI trace (`trace-event
usb_xhci_xfer_start on` via the monitor socket `~/macos-vm/run/monitor.sock`) showed a steady
~1042 isochronous packets/s, and QEMU image c513's usb-audio counters reported no odd-sized or
dropped packets. Packet sample amplitudes were not measured; the origin of the silence
remains unresolved. The raw WAV from that run is unavailable for reanalysis.

**Release 515 revalidation.** A clean 70-second single-tone capture at 4K/120
had zero silent 1 ms windows after startup during 30 seconds of stress. A
300-second single tone then produced a 289.98-second capture with zero silent
1 ms windows after startup through 240 seconds of three-window stress at mean
119.7 QEMU/macOS fps. Every active one-second spectrum was dominated by
440 Hz. A foreground Cocoa/AVAudioPlayer window plus 20 QEMU host-window
resizes produced a 99.97-second capture with zero silent 1 ms windows after
startup and 120 fps presentation. All three sessions passed native stop,
schema-2 guard release and authorizing MODE2/no-queue recovery. These results
qualify only the measured state on this host boot; they do not explain the
older report or retest Safari/YouTube.

**Insufficient interventions.** usb-audio buffer 256 ms + PulseAudio latency 80 ms (510);
48 kHz audiodev (513); variable packet sizes (513); a 200 ms display presentation
hold; and a process-only QEMU nice=0 override. The display copy poller's CPU
cost was about 17 µs per 1 ms tick in 514 statistics. The slow-drag guest
USB/`coreaudiod` interruption still needs its first scheduling cause.

**If work resumes.** Retain synchronized WAV, guest player lifetime,
USB packet amplitudes, QEMU post-mix samples and host sink output before an
audio code change. A 30 fps copier-rate A/B remains available if a failure can
be reproduced. Guest timestamps: AppleUSBAudio derives zero timestamps from
USB frame timing; a HAL/driver clock mismatch under load would make the HAL write behind the play
head (silence). `log stream --predicate 'subsystem == "com.apple.coreaudio"'` at debug level, and
`ioreg -l -c AppleUSBAudioEngine` sample/zero-timestamp counters before and during the stress.

**Repro constraint.** The failing state needs the user's monitor on. With the host display off
the virtual sink starts at 5120×2880@60 (`VSINK: resize to …` in the serial log) and macOS
presents almost nothing, so audio stays clean and A/B results are invalid. Check the stress
output's `macOS present` fps (should be ~100+) before trusting a result.

## Practical notes

- GPU hand-off after a host reboot (no sudo):
  `systemd-run --user --wait --collect --pipe pkexec --disable-internal-agent /usr/local/libexec/rgpu-gpu-bind`.
- New release: worktree from the latest candidate, bump `kext/Info.plist`, register the version
  and card pair in `tools/stage-candidate.py` (version regex, `SUPPORTED_CARD_DIAGNOSTICS`,
  `IGPU_AGENT_PAIRS`, `IGPU_CONSOLE_PAIRS`, `CANDIDATE203_FUNCTIONAL`), commit,
  `python3 -B tools/build-release.py --toolchain ~/macos-vm/build --output ~/macos-vm/run/candidate-N-dist --debug-symbols`,
  then `run/tahoe-diag-20261014/finish_build.py N metal-NNN <source card> …` writes the build
  identities and card; commit the card; `tools/install-desktop.sh --release N --card metal-NNN
  --pins experiments/pins-igpu-display-v18.json` from the worktree. The release worktree must be
  clean and its `src/` must match the card's source commit.
- A failed launcher start can leave a GPU-less guest running. Identify its full container ID
  and owning refresh service before stopping that exact trial. Preserve first-panic evidence;
  a forced stop is not native shutdown. Do not stop another active experiment by unit glob.
- An early GPU-boot panic leaves the runner waiting: SIGTERM the
  `python3 … tools/experiment.py run` process (not its `systemd-inhibit` wrapper); the launcher
  then runs the noqueue recovery.
- QEMU image builds: tree `~/macos-vm/run/c449-qemu-runtime` (patched QEMU 10.1.2 and `build/`).
  Build inside `sickcodes/docker-osx` with a ninja binary and QEMU's bundled meson wheel on
  `/python`: `docker run --rm --entrypoint sh -v ~/macos-vm/run/c449-qemu-runtime:/build -v <pybin>:/python:ro sickcodes/docker-osx:latest -c 'export PATH=/python/bin:$PATH PYTHONPATH=/python; cd /build/build && ninja -j16 qemu-system-x86_64'`,
  then `docker build -t rgpu-qemu:cNNN-igpu-display .` and a new pins file with the image id.
  Patches are recorded in `patches/qemu/`.
- In the guest's zsh, `log` is a builtin: use `/usr/bin/log show …`.
- Guest DNS is set to 1.1.1.1/8.8.8.8 (an ISP Apple-cache node was slow); a temporary
  LaunchAgent `org.raphaelgpu.clipboard` runs the clipboard agent until the console support
  package is reinstalled with the new `start-console.sh`.
