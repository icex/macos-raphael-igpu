# Handoff: HDMI output via the running DMCUB (2026-09-23 18:15 EEST)

**Historical handoff, superseded by [live status](../../../status.md).** Candidate 297 has
now run on boot 90122d1c; inbox reads were zero, delivery refused, recovery authorizes
reuse and SMU probe passes. GitHub credentials work. See repository status for details.

Goal: a picture on the user's Samsung over the Raphael iGPU HDMI port. HDMI audio comes after that
(plan: `findings/research/hdmi-audio-passthrough-20260917.md`).

## Where it stands

- Display core runs on hardware: DCN 3.02 pool on DCN 3.1.5 via register translation (cgs slot
  interposition), EDID reads work, and AppleGraphicsDevicePolicy accepts the controller with
  `rgpuagdp=1` (agdpmod=pikera rename). Details: `findings/research/dcn315-first-init-20260923.md`.
- Candidate 294 (metal-142) ran Apple's real HDMI mode set (pixel clock 333.125 MHz on PLL 0x14,
  DIG0 HDMI 4 lanes, UNIPHY A enable), but only logged the DMUB commands. The GPU then hung and the
  SMU mailbox stopped answering (MODE2 probe failed); a host reboot was needed.
- The host driver's DMCUB stays running after handoff (SCRATCH0=0x43, timer running). The guest
  never loads, starts or resets DMCUB firmware — that froze the host once (candidate 285). Keep
  that fence.
- Candidate 295/296 deliver Apple's VBIOS DMUB commands (type 128: pixel clock, encoder,
  transmitter, power gating) into the live inbox1 ring and ring INBOX1_WPTR. 296 also forces
  `DCHUBBUB_ARB_DRAM_STATE_CNTL` (3.1.5 index 0x39bc) |= 0x33, the suspected fix for the SMU wedge.
- **296 attempt d panicked** (WindowServer, `wrapDcDmubQueue+0x6b4`, page fault) on the first
  delivered command. On this host boot the DMCUB windows sit at `fb+0x7f8e5400` (≈2 GB into the
  carve-out, beyond the guest BAR); on the earlier boot they were at `fb+0x2e5400`. The survey
  logged "not visible" but delivery still wrote through the BAR aperture.
- **Candidate 297 (built, card metal-145, dry run OK, NOT launched)** fixes that: the ring is
  reached through `MM_INDEX`/`MM_INDEX_HI`/`MM_DATA` (dword offsets 0x0/0x6/0x1, bit 31 set on the
  index, like `amdgpu_device_mm_access`) when it is beyond the BAR. Delivery requires
  `dcnRingUsable` (≥2 of the host's last 4 inbox headers read back sane) and reads back every
  written command. Worktree `~/macos-vm/run/worktrees/candidate-297`, branch `candidate-297`
  (local commits, not pushed: this session had no GitHub credentials).

## Live host state at handoff

- Boot `9231ea43`. iGPU on vfio-pci, `rgpu-lan` macvtap up, host DDC trace saved at
  `run/host-ddc-trace-9231ea43.txt` (not yet decoded; EDID already works, low priority).
- **The 296 attempt d run is still active** (unit `rgpu-candidate296-dcn-1754.service`, container
  `macos-sequoia`) with a panicked guest. `run/candidate-296-attempt-d-results/stop-requested`
  was touched at ~18:03 and not yet honoured (the hold loop is probably not reached while the
  harness waits for the guest agent). Let it time out or stop it through the harness; do not kill
  the runner (a killed runner loses shutdown/recovery receipts). If there's no valid recovery receipt
  (`run/vfio-recovery/9231ea43-…/<run>.json`), same-boot reuse is refused: reboot, then
  `sudo ~/macos-vm/gpu-bind.sh` (user runs it).
- The boot ledger for 9231ea43 was corrected: the first attempt's entry was removed because QEMU
  exited in `-audiodev` init before VFIO opened. Backup and note are in `run/used-gpu-boots-corrections/`.

## Harness gotchas learned today

- After a reboot with no desktop login, PipeWire/Pulse is not running; QEMU (AUDIO=usb) exits at
  once. Fixed: the launcher now starts the user audio services and requires `pactl info`
  (commit ab48022, deployed to `~/macos-vm/macos-vm.sh`).
- `gpu-bind.sh` aborted silently (set -e + pipefail on the connector match). Fixed in 11334dc and
  deployed.
- Retry namespaces (`--attempt X`) need `run/candidate-N-attempt-X/` with `build-manifest.json`
  and `RaphaelGPU.kext` copied from `run/candidate-N/`, plus
  `run/candidate-N-attempt-X-build-identities.json` with `extracted_candidate` pointing at the
  attempt dir. A used attempt dir cannot be reused ("run ID already selected").
- The run writes `status.md` into the worktree; commit it before the next cycle (dirty refusal).
- New candidate: bump `kext/Info.plist`, and in `tools/stage-candidate.py` add the version regex,
  the range text, the `SUPPORTED_CARD_DIAGNOSTICS` entry, the functional boot-args dict entry and
  the pair-list entry. Build: `tools/build-release.py --toolchain ~/macos-vm/build --output
  run/candidate-N-dist --debug-symbols`, unzip into `run/candidate-N/`, write identities and card
  (see the 297 commit for the exact script shape). Launch scripts: `run/cNNN-launch.sh`
  (systemd-run wrapper around `tools/cycle.py`).

## Next steps

1. Get the GPU free: finish/stop the 296-d run cleanly, or reboot + gpu-bind.
2. Launch 297: `~/macos-vm/run/c297-launch.sh`. Watch `run/serial.log` for
   `DMCUB inbox ring usable|UNUSABLE`, `DMUB delivered`, `DMUB TIMEOUT`, `readback`,
   `DCN: DRAM_STATE_CNTL`, `panic(`. Ask the user whether the Samsung shows anything.
3. If commands are consumed but no picture: check OTG enable/CRC, DIG/PHY state and pixel clock
   against the host trace; confirm that the SMU still answers at the next MODE2 probe.
4. After every hardware run: update `status.md`, then merge candidates 291–297 into `dev` (dev is at
   7075255, candidates ≤290) and push once credentials work.
