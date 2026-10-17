# Candidate 445: iGPU display engine as the QEMU display — first survey

User direction (2026-10-11): no mirror and no second display; the Raphael iGPU drives its own
display and QEMU shows that output directly, eventually without any HDMI plug. The October
console cards (metal-223…238) omit the whole DCN/HDMI configuration and present a
CGVirtualDisplay copied by ScreenCaptureKit into QEMU `bochs-display`; macOS additionally
binds Apple's `AppleBochVGAFB` to that device, which is the second "85 Hz" display (all of its
modes are labelled 85 Hz) that the presenter mirrors onto the virtual display.

## Run

Candidate 445 / metal-239: the exact candidate 330 (metal-178) display configuration on the
current 444 driver source (`d1deade…`, build `0262f4b0406147b6b647eab04de89f28`), without HDMI
audio because function 1 (`7b:00.1`) is held by `snd_hda_intel` this boot. No virtual display,
no Bochs device, no GENERIC graphics. A dummy HDMI adapter is on the iGPU port. Boot
`ba51b3c6…`, MODE2 347, run `9f601e6566dc1eebe20bebb8e95583cd`.

## Results

- macOS has exactly one display: the dummy sink "HDP-V104" on the AMD framebuffer,
  3840×2160 backing / 1920×1080 HiDPI, reported 60 Hz, not mirrored (79 modes, 24–60 Hz).
- Read-only DCN register survey through the QEMU monitor (`.research/c445-dcn-survey.py`):
  only HUBP0/OTG0 active. Primary surface MC `0xf400700000` = framebuffer offset 7 MiB, inside
  the 256 MiB BAR0. `SURFACE_PIXEL_FORMAT=8` (ARGB8888), `SW_MODE=0` (linear), DCC off,
  viewport 3840×2160, pitch 3840 px. The address did not change across samples (no flip seen).
  DCN_VM FB location `0xf4000000000–0xf47fffffff`, FB offset `0x7e0000000`.
- OTG0 timing 4000×2222 total; its frame counter advances at **67.5 Hz** (675 frames in
  10.0 s), i.e. a ~600 MHz pixel clock instead of the ~533 MHz this 60 Hz mode needs. The
  stream clock appears to be set to the 600 MHz link maximum; macOS still reports 60 Hz.
- QEMU reads of BAR0 run at **21.8 MB/s** (uncached vfio mapping) versus 1.7–3.2 GB/s for guest
  RAM (33 MB `pmemsave`, two repeats each). Polling the scanout through BAR0 cannot reach even
  1 frame/s at 4K.
- **The GPU accelerator never attached.** `AMDRadeonX6000` loaded, HWServices powered up
  (`XI: PowerPlay…`), but no `AMDNavi23GraphicsAccelerator`, no `powerUpHW`, no RLC/GART
  bring-up, no recovery lease (`XH2 OWNED/POOL`). WindowServer composites in software
  (`CompositorSW` / `CA::OGL::SWContext`, ~109% CPU) and the sampled scanout was uniformly
  black. Candidate 330 with the same arguments on its own source did reach `powerUpHW` and the
  lease pool. Apple's accelerator log shows `TTL::initialize() Failed! Error code: 0xe00002bc`
  130 ms after starting (PSP status registers read all-ones before TTL, as they also do on 444,
  where TTL succeeds). The DCN trace dropped 108,087 lines and the driver log is a third of
  330's, so the pre-TTL diagnostics are incomplete. The harness therefore never ran the probe (readiness `INCONCLUSIVE`,
  `recovery_lease_pool_missing`) and the run ended at its launch deadline.

## Consequences for a GPU-native QEMU display

1. Regression first: find what between 330 and 444 stops the accelerator attaching when the
   display engine is enabled (compare the 330/445 logs around `dc_hardware_init`, then bisect
   the DCN-related source changes).
2. Fix the stream clock so the OTG runs at the advertised 30/60/120 Hz.
3. Transport: the scanout is linear ARGB8888, which suits QEMU, but BAR0 is uncached. Options,
   in order of preference: scan out from guest system memory (GTT) so QEMU reads ordinary
   guest RAM with no copy; or a GPU (SDMA) copy per vblank into a guest-RAM buffer; or a
   cached host mapping of the carve-out (root). QEMU then presents it as a graphic console of
   the vfio device itself, with no extra guest-visible display device.
4. No plug: once the above works with the dummy, emulate the sink (HPD + EDID) in the driver.

Evidence: [survey JSON](igpu-native-display-survey-evidence-20261011.json);
`~/macos-vm/run/candidate-445-*`, `c445-*`.
