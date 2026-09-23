# Live status — 2026-09-17

**Candidate 285 froze the host. The cause is localized and removed; no GPU guest is running.**
[Crash analysis](findings/research/dcn315-dmcub-host-crash-20260917.md).

- **Host fault:** run `6a14565ae903af4ba86bdd91315fc629` (candidate 285, metal-133, MODE2#188, boot
  `7ee81442`) froze the whole machine about eight seconds into the guest boot, during HWLibs
  TTL/PSP init. There was no kernel message, pstore, MCE or BERT record. The only new code that
  ran was `rgpudcn` bit 8, which registered Raphael's DMCUB firmware for PSP from the guest. The
  display core never ran. There is no shutdown or recovery receipt for this launch.
- **Change:** candidate 286 removes the guest DMCUB firmware path and refuses bit 8. It fences off
  DMCUB: the strap reads as absent, every DMCUB write is dropped, and the DCN 3.02 pool is only
  selected after the register interposition is live. HDMI PHY/pixel-clock bring-up needs DMCUB, so
  it is blocked until DMCUB can be started without a guest-initiated load.
- **Display port (candidates 285/286):** Apple's DC 3.2.145 is steered onto its DCN 3.02 pool with
  DCN 3.0.2 to 3.1.5 register translation (307 moves, 1484 drops, pipe power domains, 9 field
  remaps). The Navi DALSMC mailbox is emulated. This is untested on hardware.
- **Host now:** boot `365fcd4e-6d9d-420f-a006-5ab784a4cd0d`. GPU 0000:7b:00.0 is back on `amdgpu`
  after the power cycle and needs the root `gpu-bind.sh` handoff before any run.
- **120Hz:** the CoreDisplay patch is built into candidate 285/286 behind `rgpuvd120=1` and has not
  yet run. Its r14 = entry+0x30 assumption must be checked by disassembly in the guest first.
- **Streaming (candidate 284, merged):** stable 4K60. The VCN preset fix gives 88fps at 4K HEVC.
  The UMA carve-out is 2GB. Guest Sunshine uses ScreenCaptureKit.
  [Evidence](findings/research/encoder-pipeline-20260917.md).

## CI portability — 2026-09-17

Run `35143887854` failed on missing NumPy/Pillow, shallow Git history, a local-only
Lilu fixture and host KVM permissions. The repair supplies the CI dependencies and
history and makes both fixture tests independent of host installations. Local
validation: 965 Python tests OK (3 skipped), both software-UART qualifications
and all CI C++/sanitizer checks pass. Hosted validation follows on `dev`; this
changes no hardware qualification or launch authority.

## Guest audio — 2026-09-22

The user needs audio while using the VM over VNC/streaming. HDMI audio stays gated on the display
link and DMCUB, so candidate 286 gets a host-backed output first: launch option `AUDIO=usb`
replaces the image's driverless HDA codec with a QEMU `usb-audio` device on the host PipeWire
pulse socket, driven by macOS's own USB audio class driver (no guest kext, no root).
Launcher, entry script, harness contract and staging admit it; card `metal-134` carries it;
999 host tests OK (3 skipped); container QEMU connects to PipeWire and creates the device.
**Run 2026-09-22 (candidate 286, metal-134, run `04abf9aa923b43423685faadc2551432`, boot
`67ab8c3f`, MODE2 #189):** verified. macOS lists the QEMU USB device as default output
(2ch, 48kHz, USB transport), playback starts its engine, and the host sees an uncorked QEMU
stream on the default sink. Desktop Metal probe OK (zero mismatches). In the guest, BlackHole
2ch 0.7.1 is installed (hash checked against the Homebrew cask), a stacked multi-output device
"Raphael Multi-Output" (USB + BlackHole) is the default output, and Sunshine's `audio_sink` is
`BlackHole 2ch`; Sunshine plus the LAN relay were up at `192.168.0.43:48989` for the user's
Moonlight test. The display hook attached its three routes but found the `cgs_device`
read/write slots empty (`read=0 write=0 -> NOT interposed`), so translation and the DCN 3.02
pool stayed off and DC ran its usual DCN 2.0 path (40 named waits, no panic): the slot
offsets need re-deriving from a live `dc_context`.
[Notes](findings/research/hdmi-audio-passthrough-20260917.md).

## LAN, Screen Sharing and client size — 2026-09-22 evening

The guest now has a second NIC bridged on the LAN (macvtap `rgpu-lan`, fixed `192.168.0.44`,
primary service), which is what Apple Screen Sharing's High Performance mode needed; port
forwards cannot carry it. RealVNC, Apple standard mode and High Performance mode work at
`.44`; Sunshine listens there too. The fallback display can adopt a client's size with
`remote-retina --size WxH`; a persistent virtual display was tried and is unusable here (1 s
capture latency). [Notes](findings/research/lan-bridged-screen-sharing-20260922.md).
Per boot the user runs the three root commands from the notes; the launcher does the rest.
Evening: Moonlight video+audio work at `.44`; RealVNC works; Apple High Performance mode streamed
only right after a login at 1920x1080 Retina with Mac login, and breaks after any display mode
switch (stale scale until a WindowServer restart); Apple client audio tap fails; client
resolution never works. Sessions can now last 12 h. Details in the notes.

## EDID works — 2026-09-23 15:40

Fresh boot: the guest read the dummy adapter's EDID at boot and the Samsung's after a hot-plug
(full I2C trace). The 287–290 NACKs were the adapter's EEPROM locked by the morning's host
freeze, not the guest. Display core state: sink detected, no display published; the link needs
DMUB (init logs "Error queuing DMUB command"). Next design: attach DAL to the DMCUB firmware the
host driver left running, without loading or resetting it.
[Notes](findings/research/dcn315-first-init-20260923.md).

## Candidates 288–290 — 2026-09-23 afternoon

The EDID read on the HDMI plug is a clean NACK of address 0xa0 by the plug, with the engine,
pad mode, pull-downs, memory power and bus timing all matching what Linux programs (288: I2C
memory was awake; 289: full transaction trace; 290: host timing replayed, engine clock 24 MHz).
Next: `sudo tools/host-ddc-trace.sh` on a fresh host boot (iGPU on amdgpu) and diff the host's
register sequence against the guest's with `tools/dcn-trace-decode.py --host-trace`.
[Notes](findings/research/dcn315-first-init-20260923.md).

## Candidate 287 ran — 2026-09-23 13:30

First launch froze the host in the PSP phase (that boot had been suspended overnight with the
iGPU on vfio-pci; the display hook never ran). On the fresh boot the display core initialised on
hardware for the first time: cgs slots interposed, DCN 3.02 pool, 593 translated accesses and
34 waits with no panic; DMCUB untouched and still booted from the host driver; HPD sense high on
the HDMI plug; the EDID read on DDC1 completed but returned 0xFF. Next evidence needs a host
reboot: the host driver's I2C/pad registers via `dcn-state-probe.py`.
[Notes](findings/research/dcn315-first-init-20260923.md).

## Candidate 287 ready — 2026-09-22 22:45

Built and preflighted (1000 tests): the display hook's cgs pointer check now accepts the
auxiliary kext collection range, which is why metal-134 never interposed the DAL registers.
Run `run/c287-launch.sh` (card metal-135, rgpudcn=23, AUDIO=usb) once the user's 12-hour test
session on candidate 286 ends (Wed 09:59 or earlier by stop file). Remote display: the virtual
display's 1.2 s capture latency is a ScreenCaptureKit metric, not VBL; a permissioned SCKit
probe is the next measurement. [Notes](findings/research/lan-bridged-screen-sharing-20260922.md).

## Next session (display and HDMI audio are the user's priority)

1. **Host.** The iGPU is on `amdgpu` in boot `365fcd4e`. A guest run needs the user to run
   `sudo ~/macos-vm/gpu-bind.sh`. The candidate 285 launch has no recovery receipt; this is a
   fresh boot.
2. **Get the user's agreement, then run candidate 286 / metal-134.** It is built, its identity
   is recorded, and its card is committed on branch `candidate-286`. Launch with
   `run/c286-launch.sh` (systemd-run, cycle.py). Expected outcome:
   - the guest lists the QEMU USB audio device as its output and a sound reaches the host sink;
   - the DCN 3.02 pool builds without a panic or host fault;
   - the DCN wait and trace lines name the registers;
   - HPD and EDID are read over DDC1 from the dummy plug;
   - no picture, because DMCUB is absent;
   - DMCUB stays untouched (`DCN: DMCUB ... CNTL/SCRATCH0` unchanged, no blocked writes that
     matter).
   In the interactive hold, disassemble CoreDisplay's `_CGXVirtualDisplayApply` in WindowServer
   to confirm the `rgpuvd120` r14 = entry+0x30 assumption before enabling it.
3. **DMCUB decision (blocks HDMI output).** Never load, start or reset DMCUB from the guest.
   Next evidence is read-only: dump the DMCUB windows under a working host amdgpu (root). Then
   discuss options with the user: keep the host-loaded firmware alive across the handoff, or
   another route. See [display port plan](findings/research/display-dcn315-port-20260917.md) §5.
4. **HDMI audio** follows the display link:
   [plan](findings/research/hdmi-audio-passthrough-20260917.md) (spoof ab28, AppleGFXHDA pairing
   patch, root bind of 7b:00.1, launcher gates).
5. **Real monitor.** The iGPU HDMI port has a dummy plug. Ask the user to connect a real monitor
   only after EDID, link and OTG CRC evidence.

## Verified progress

| Area | Evidence and scope |
|---|---|
| Managed texture ownership | 96 cases;111,658,032 pixel comparisons; synchronized CPU writes and retained LOAD color contents, zero mismatches |
| Cross-process GPU events | Typed XPC import;33 consumer-first transfers,25,453,131 correct pixels |
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| Stock QEMU / PerfPowerServices | OpenCore/VirtualSMC fix passes two guest boots,0.0% CPU, latest0.86s; prior patched-QEMU evidence retained separately |
| Host regression | 965 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Prior qualified280 driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).


## Remaining roadmap

1. Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
   then qualify login persistence.90/120Hz modes remain unproven.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. Existing clean stops do not qualify every failure mode.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release. Historical direct OpenGL hang and live Metal validation crash remain open.
4. Physical DCN output, other hypervisors and measured performance/release qualification.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in this tested setup;
PerfPowerServices was0.0% CPU on two guest boots. Automatic required-hardware HEVC
decode works; explicit GPU-ID selection remains limited. Main10 decode has scoped
passes; hardware encode is Main8. [Roadmap](docs/ROADMAP.md).

After milestones update current docs, integrate/push dev and synchronize the local
checkout. Do not push main without new authorization. Prior live entries are [archived](findings/research/status-archives/status-before-display-port-20260917.md)
and [earlier](findings/research/status-archives/status-before-night-close-20260916.md).




## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-286-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-286-attempt-udp-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-286-attempt-lan-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-286-attempt-lan2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-290-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
