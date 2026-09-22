# HDMI audio for the passed-through Raphael iGPU — plan, 2026-09-17

## Update 2026-09-22 — guest audio for remote use goes through a USB audio device first

The user's need is audio while using the VM over Screen Sharing/VNC and streaming, not sound on
the HDMI port itself. HDMI audio (below) is gated on the display link, and that link is gated on
DMCUB, which the guest must not start. So the guest gets a host-backed audio output first:

- **Mechanism [V]:** launch option `AUDIO=usb`. `tools/macos-vm.sh` mounts the host pulse
  socket (PipeWire) into the container and `tools/vm-entry.sh` rewrites the image's
  `-audiodev ${AUDIO_DRIVER},id=hda -device ich9-intel-hda -device hda-duplex,audiodev=hda` into
  `-audiodev pa,id=hda -device usb-audio,audiodev=hda,bus=xhci.0`, fail-closed (exactly one
  usb-audio device, no HDA codec left, image xhci controller required). Guest sound then plays
  on the host's default sink, next to the VNC viewer.
- **Why USB, not the image's HDA codec [V]:** the guest has no driver for QEMU's HDA codec
  (AppleALC is disabled and has no entry for it; no VoodooHDA on the host), so past guests had no
  audio device at all. macOS drives a USB audio class device with its own `AppleUSBAudio`, so no
  guest kext, no OpenCore change and no host root work.
- **Harness [V]:** `experiment.py launch_options` admits `AUDIO=usb` only on the display-less and
  debugger contracts; `validate_running` requires exactly one `usb-audio` on `xhci.0` when the
  option is set and refuses one otherwise. `stage-candidate.py` accepts the option for the
  functional card contract. Card `metal-134` (candidate 286) carries it.
- **Smoke test [V]:** the container QEMU 10.1.2 connects to the host PipeWire pulse socket as
  the container user and instantiates `usb-audio` (only benign `set_sink_input_volume` warnings).
  The deployed `vm-entry.sh` transforms the real image `Launch.sh` correctly (dry run, 52 argv).
- **Streaming caveat [I]:** Sunshine on macOS captures audio from an *input* device named by
  `audio_sink`; a plain output device is not enough. Moonlight audio therefore also needs a
  loopback such as BlackHole 2ch (`https://existential.audio/downloads/BlackHole2ch-0.7.1.pkg`,
  sha256 `57b540f27a3e29c37e310e01bee0fdfab76733087e47f997ef9dccf851400dcf`, per the Homebrew
  cask) installed in the guest and selected as output. Not done yet.
- **Guest check for the metal-134 run:** `system_profiler SPAudioDataType` lists the USB
  device as default output; `afplay /System/Library/Sounds/Glass.aiff` produces a QEMU
  sink-input on the host (`pactl list sink-inputs`).


Research only. No device was bound and no VM was run for this. **[V]** verified in a binary, a
plist, a source file or live sysfs. **[I]** inferred.

End-to-end audio needs a working HDMI stream: AppleGFXHDA only publishes an output after an
`AppleDisplay` with a CEA audio EDID appears under the GPU. So it is gated on the
[DCN 3.1.5 display port](display-dcn315-port-20260917.md). The plumbing below can be prepared
independently.

## Findings

1. **Device ID must be spoofed [V].**
   - 7b:00.1 is `1002:1640`. AppleGFXHDA's AMD personality (`AppleGFXHDAEGController`) matches
     `IOPCIMatch 0xAAF81002 0xAAF01002 0xABF81002 0xAB201002 0xAAE01002 0xAB381002 0xAB281002`.
   - AppleHDAController class-matches but its probe (0x20ea) rejects the device (it needs HDEF/HDAU
     or `hdax=1`, and has no 1640/ab28 table entry).
   - Use **`1002:ab28`** (Navi 21/23 HDMI audio, the partner of the 73ff GPU spoof).
2. **The spoof must be in config space [V].** `AppleGFXHDAController::probe` (0x267c) reads the
   vendor and device IDs with `extendedConfigRead16` and checks a 12-entry table (0x5e320). So use
   QEMU `x-pci-vendor-id=0x1002,x-pci-device-id=0xab28`; an OpenCore `device-id` alone is not enough.
   For codec 0x1002aa01 (the host codec: "ATI R6xx HDMI", pins 0x03..0x0b), ab28 selects
   `FunctionGroupATI_Tahiti`; 1640 selects nothing.
3. **No OpenCore DeviceProperties are needed [V].** `hda-gfx`, `layout-id` and the HDAU rename are
   not read on the AMD path; the probe score is 100 without `layout-id`.
4. **GPU pairing patch (likely needed).**
   - `EG::locateAssociatedGraphicsController` (0x2ae52) pairs with the first sibling under the
     parent bridge whose **bus number** matches (call sites 0x2af1d, 0x2af30) [V].
   - On QEMU `pcie.0` every device is on bus 0, so it would probably pick 00:00.0 or 00:1f.x [I].
   - A 2-byte Lilu patch compares the device number instead (vtable slot 0x8e8 → 0x8f0; the pattern
     is unique in the kext) [V]:
     `48 8b 00 4c 89 f7 ff 90 e8 08 00 00 4d 89 fd 41 89 c7 48 8b 7d d0 48 8b 07 ff 90 e8 08 00 00 41 38 c7`
     with both `e8 08` replaced by `f0 08`.
   - Verify with `ioreg`: `HDAU BDF` 0x3001, `GFX BDF` 0x3000.
   - The GPU cannot move behind a root port (`tools/macos-vm.sh`: macOS tears down the BARs).
5. **Framebuffer side [V].**
   - `reportCapabilities_LinkInfo` (0xe074) publishes `av-signal-type` (HDMI = 8) and
     `audio-codec-info` (table 0x22757c: 0x30100, 0x50100, … = pin NID<<16 | 0x100).
   - `setAttributeForConnection 'aud '` (0x35c80) is a no-op; audio is enabled inside DAL:
     `dce_aud_az_enable` 0x16137c, `az_configure` 0x161590, `wall_dto_setup` 0x161ad1,
     `enc3_se_setup_hdmi_audio` 0xacc2e.
   - Boot-arg `audio-codec-info=<u32>` overrides the pin for debugging.
6. **DCN 3.1.5 audio needs [V]:**
   - `num_audio=5` and the AZF0ENDPOINT registers (same addresses on 3.0.2/3.1.5);
   - clear `DCCG_AUDIO_DTO_SEL` bit 6;
   - power up `VPG0_VPG_MEM_PWR` (BAR5 0x154B4) before infoframes;
   - PME message VBIOSSMC 0x0D (not DALSMC 0x11). Guest SMU messages carry host risk; agree them first.

   The CORB/RIRB "base idx 3 far offsets" in `dcn_3_1_5_offset.h` belong to 7b:00.1's own BAR,
   not BAR5.

## Host prerequisites for 7b:00.1

- **Live state [V]:**
  - `snd_hda_intel`, D3hot, `reset_method=pm`, alone in IOMMU group 32;
  - a device link to 7b:00.0 (`quirk_gpu_hda`);
  - vfio-pci `disable_idle_d3=N`.
- **Bind at runtime, same boot, after amdgpu initialized 7b:00.0.** This is root work, like
  `gpu-bind.sh`:
  1. `driver_override=vfio-pci`;
  2. unbind `snd_hda_intel`, then `drivers_probe`;
  3. empty `reset_method`;
  4. `power/control=on` **after** bind;
  5. `chown` `/dev/vfio/32` to the user.

  Optional udev nopm rule for 1640. Do **not** bind it at boot.
- **Never unbind it from vfio-pci within the boot:** assume the 7b:00.0 unbind oops applies.
- **Bus reset stays impossible** only while .2/.3/.4/.6 remain host-owned. Never pass those through.

## Launcher and gate changes (opt-in, default off)

- **`tools/macos-vm.sh`:**
  - add `multifunction=on` to the GPU `-device`;
  - add `-device vfio-pci,host=0000:7b:00.1,bus=pcie.0,addr=0x6.0x1,x-pci-vendor-id=0x1002,x-pci-device-id=0xab28,rombar=0`;
  - add docker `--device /dev/vfio/32`;
  - repeat the driver, reset and power checks for .1.
  - The deployed `~/macos-vm/macos-vm.sh` differs from the repo copy (local diagnostics); merge
    carefully.
- **`tools/experiment.py`:**
  - `validate_running` rejects `len(vfio) != 1` and checks the slot-6 occupants;
  - `host_snapshot`/admission read only 7b:00.0;
  - the reset-message regexes are `7b:00\.0`;
  - the launch args add the audio flags;
  - harness hashes change.
- **`tools/vm-supervision.py`:** blank the new environment variables (like `GPU*`).
- **`tools/cycle.py`:** preflight must check .1.
- **`examples/qemu/raphael-vfio.cfg`:** add the second device.

## Order

1. Display port works (HDMI stream up).
2. Add the gated AppleGFXHDA patch and the launcher/gate changes.
3. User binds .1.
4. Boot and check `HDAU BDF`/`GFX BDF`, codec enumeration and a clean host journal.
5. Play to the HDMI output; sweep `audio-codec-info` if it is silent.
