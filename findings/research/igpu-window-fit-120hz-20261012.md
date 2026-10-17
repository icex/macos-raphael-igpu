# Candidates 454–455: window-fit resolutions, HiDPI/1x choice, 120 Hz, verified exits

## Window fit with HiDPI and low-DPI choices (455)

Each QEMU window resize (stable 1 s) produces one display whose EDID offers:
- a **HiDPI panel** 3840 pixels wide in the window's aspect (60 Hz) — macOS lists its Retina
  "looks like" sizes and the viewer scales the picture into the window; and
- the window's **exact pixel size at 1x** (low DPI, shown 1:1), at 120 Hz when the host
  refreshes at >= 100 Hz and one display pipe can drive it, plus 60 Hz.

The guest helper (`guest/display-helper`, root LaunchDaemon) receives the kext's request
(`RGPUDisplayOverride` on the framebuffer) and selects HiDPI "looks like panel/2" by default
or the exact mode with `defaults write /Library/Preferences/org.raphaelgpu.display dpi low`.

Measured (455 run, QEMU image 076e6f38…): default → "looks like 1920x1080" at 2x on 3840x2160;
`dpi low` with a 1600x1000 window → 1600x1000 at 1x **120 Hz**; full-screen Metal motion
**119.71 distinct frames/s over 65 s** into QEMU's window (8989 frames rendered in 75 s, one
writeback overflow flag). At 4K Retina (453): 59.95 distinct frames/s over 65 s.

## Why not HiDPI at every exact size

macOS 15.7.9 creates 2x modes on its own only for 4K-class panels (3840x2160/3840x2400 yes;
3200x1800, 3280x2160, 3360x2100 no). Display overrides in /Library/Displays are not read at
all: IODisplayCreateInfoDictionary uses only the sealed /System/Library/Displays bundle, even
for never-seen product IDs and on a fresh query (454; a probe DisplayProductName was not
picked up). HiDPI at arbitrary sizes would need a CoreDisplay userspace patch.

## 120 Hz limits

One pipe's pixel clock comes from the DP DTO (≤ 600 MHz reference): 2560x1440@120 (497 MHz)
and smaller fit, so writeback delivers 120 full frames/s there. 3840x2160@120 (~1.08 GHz) needs
ODM 2:1, and DWB then sees only one 1920-wide segment (one writeback unit, tap before the ODM
merge; RE notes ~/macos-vm/run/c454-odm-4k120-notes.md). Retina 1080p at 120 Hz therefore
needs a different transport: copying the scanout surface per flip.

## Reliability

- Harness: direct-manager runs now bind capture-exit receipts to the manifest run and
  admission digest; 454 is the first direct run with a verified `exited-after-guest-request`
  (both channels natural container exit). 452's old classification was right: Docker
  recorded exit 137 (killed while exiting).
- Fresh boot: `smu-mode2-reset --halt-running-dmcub` (cards with `rgpudcncold=1`) halts a
  fresh boot's running DMCUB to the empty post-resume state (Linux dmub_dcn31_reset order,
  then windows/regions cleared). Unit-tested; not yet exercised on a fresh boot.

Runs: 453 `343e8eee…` CORE_PROBE_PASS; 454 `5fbe46c5…` CORE_PROBE_PASS, verified exit, recovered;
455 live. Evidence: ~/macos-vm/run/c453-metal-fullfield65-wbstat.json,
c455-120hz-fullfield65.json, candidate-45{3,4,5}-results.
