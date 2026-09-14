# Roadmap

Rewritten 2026-09-14, against candidate **1.0.230**. This file is the authoritative plan.
Live run state lives in [status.md](../status.md); historical narrative lives in `findings/`.

**Objective:** correct, usable macOS desktop acceleration on the Raphael iGPU, with a display
path that can be watched and a repeatable lifecycle, while never endangering the host.

## Where we are

| Milestone | State |
|---|---|
| Device enumeration, ROM synthesis, HWLibs dispatch | done |
| Native accelerator startup, KIQ, command submission | done |
| Compute + offscreen render/readback | done |
| Desktop composition through Metal on the Raphael GPU | done (`rgpunobin=1`, `rgpusdmacfg=2`) |
| Managed-texture copy correctness | done (`rgputexdiag=2`, per-process bit-27 patch) |
| Same-boot relaunch without reboot | done (`tools/smu-mode2-reset.py`) |
| Guest sleep/wake with GPU resume | works; host-driven clean shutdown does not |
| Visible display output | **virtual only** — no DCN 3.1.5 in Apple's framebuffer |
| Remote-session rendering artifacts | **undiagnosed** |
| Game / performance qualification | not started |
| Remote-session "corruption" | **strong evidence: a lossy remote-transport artifact, not a GPU defect — one confirming test left** |

## 1. Diagnose the 8×8 block artifacts seen over remote desktop — near-closed (2026-09-14)

**Strong evidence that the artifacts are a lossy remote-desktop transport artifact, not a GPU or
compositor defect.** The discriminating test in the plan below ran and came back negative for a
GPU cause; one confound remains before it is fully closed.

Sparse thin green shards appeared over translucent/vibrancy regions (Finder sidebar, Safari start
page, menu bar) in a screenshot of the remote client window on the Linux host; opaque interiors
and bare wallpaper were clean. A **lossless in-guest `screencapture`** of the same desktop — same
Safari start page, same Favorites row, same translucent Privacy Report card and menu bar — is
**clean**: the only green regions are legitimate UI (Dock icons, the TripAdvisor tile, a menu-bar
icon), and every translucent region is smooth. The shards also sit at a 2/5 sub-tile offset (not
the origin-aligned GFX10 micro-tile grid) and only over dithered translucency — a lossy codec
signature, never a GPU tiling one. pipeBankXor and DCC/fast-clear are excluded for the desktop.

The user reports the same shards over **VNC** as well as NoMachine. That is consistent: Apple
Screen Sharing and NoMachine are both lossy by default, so both smear these gradient regions. A
lossy *transport*, not a specific product, is the cause.

Evidence and quantified comparison: `findings/research/desktop-corruption-diagnosed-20260914/`
(`in-guest-lossless-clean-1280x1024.png` vs `remote-nomachine-client-corrupted-1944x1121.png`,
side-by-side in `remote-vs-inguest-comparison.png`).

**Remaining to fully close it** — two confounds: (a) the clean capture is a different frame and
resolution (1280×1024) than the corrupted ones (~1920 wide, a Displays pane was in use between
them), and the shards are sparse/possibly intermittent, so a clean snapshot is not proof a
*simultaneously* corrupted frame was clean in the framebuffer; (b) the user's VNC path is assumed
lossy but unconfirmed. **The confirming test:** on the next GPU desktop session, grab one
artifacted frame two ways at once — a **forced-lossless / raw-encoding VNC** capture (`vncviewer
-PreferredEncoding=Raw -AutoSelect=0 -FullColour`, or `-QualityLevel 9 -CompressLevel 0`) and an
**in-guest `screencapture`** of the same moment. Raw-VNC clean while the lossy view shows shards ⇒
transport, proven. Raw-VNC still showing shards ⇒ framebuffer implicated, reopen as a GPU
question. `tools/vnc-frame-capture.py` is the scripted path — force raw encoding on it first. The
deeper poison-pattern DCC/tiling probe (`findings/research/desktop-corruption-diagnosed-20260914/
dcc_wedge_probe.m`) is kept for that reopen case.

Consequence (pending the confirming test): **very likely no GPU fix is needed.** To watch the
desktop without artifacts, use a lossless transport (raw-encoding VNC, or max NoMachine quality)
or wire the AMD scanout to a presentable surface (item 3), which removes the codec from the path.

## 2. Make the Metal patch survive macOS updates

The bit-27 patch is currently pinned to the 24G830 driver UUID, a fixed `__TEXT` offset
(`0x13a7e1`) and exact instruction bytes. After any system update it safely **skips**, and the
managed-texture defect returns silently.

Make the locator structural instead, keeping fail-closed behaviour:

- Derive the bit number from the driver's own `__objc_methtype` `AMD_DeviceSettings` metadata by
  counting the ordered one-bit fields, rather than hard-coding 27.
- Find the settings constructor by a *name cluster* (`enableTexturePipeBankXor` adjacent to
  `enableBlitDMA`, `enableLinearMSAABlit`) plus the repeated setting-helper call shape.
- Validate the candidate instruction's read/merge/store dataflow and require exactly one match;
  refuse on ambiguity, missing metadata, or an already-clear bit.
- Keep the UUID/path checks as provenance guards, not as the locator.

**Status: the locator is built and validated offline.** `src/TextureSettingLocator.hpp` derives
the bit index from `__objc_methtype` and finds the constructor by instruction *shape*:

```
48 b8 <imm64>    movabs r64, imm64      (the default-enabled mask)
48 09 /r         or     r64, r64        (merge the computed bits)
48 89 /r         mov    [rdi], r64      (store into the settings object)
```

restricted to immediates that actually have the target bit set. All three encodings are
fixed-length, so **no disassembler is needed and it can run in the kernel**. Against the real
24G830 `__TEXT` this matches exactly one site — `0x13a7e1`, the known address — with no UUID, no
hard-coded offset and no hard-coded bit. `tests/test_texture_setting_locator.cpp` covers
renumbering, moved code, changed defaults, ambiguity, changed shape and malformed metadata, and
runs in CI.

An earlier prototype under `findings/research/update-resilience-20260914/` took a different route
(capstone, matching a ten-instruction sequence). It is superseded: it cannot run in a kext, its
pattern is far more brittle, and capstone is not installed on this host, so its recorded
"11 passing checks" cannot be reproduced here.

**Remaining:** wire the locator into the live COW path — read `__objc_methtype` and `__text` from
the target process, locate once, cache the offset per boot, then verify-and-apply per process.
Land it behind a new opt-in boot arg so the proven `rgputexdiag=2` path is untouched until a
hardware run validates the replacement. Scope: compatible updates within the same major version;
a redesigned settings constructor is refused, not guessed at.

## 3. Virtual display attached to the iGPU

**Now a hard prerequisite, not a convenience (2026-09-14).** The guest had **no display of its
own**: its only framebuffer was the virtual display **NoMachine** installed. When NoMachine was
uninstalled, macOS was left genuinely headless and `screensharingd` began failing with
`getactivedisplaylist error 268435459` / `unable to get width and height of display`, with
`IOFramebuffer` node count **0** on a clean boot. Every VNC client — Apple Screen Sharing,
TigerVNC, RealVNC, and a hand-written RAW/VncAuth client — then completes the TCP connect and
hangs, because the server cannot report a screen size. Apple's framebuffer carries no DCN 3.1.5,
so nothing else supplies a scanout. Until this item lands, a watchable desktop depends on a
third-party virtual display, which also puts a lossy codec back in the path and blocks the
lossless artifact verification in item 1.

**Correction and findings from the 2026-09-14 investigation.** The display was never NoMachine's:
the saved config names `IODisplayLocation = VirtDisplay8`, `DisplayVendorID` 1970170734 (`unkn`)
and `DisplayProductID` 1986622068 (`virt`) — macOS's *own* virtual display, and the
candidate-211 notes record it at 02:10, hours before NoMachine was installed. What is established:

- The virtual display is **unstable, not merely absent**. It served 1280x1024 at 15:01, a
  1920x1080 desktop at 16:37 after the resolution was changed in the Displays pane, 1280x1024
  again at 19:06, and then vanished entirely.
- `screensharingd` then fails `getactivedisplaylist error 268435459` / `unable to get width and
  height of display`, with `no agent on console` and `agent port for screen monitoring 0`, so
  every VNC client completes the TCP connect and hangs. This is reproducible across six boots and
  a MODE2 reset, and survives moving both `com.apple.windowserver.plist` display configs aside
  (backed up in the guest at `/var/root/wsprefs-aside`).
- Any display-subsystem query (`system_profiler SPDisplaysDataType`, `ioreg -c IODisplayConnect`)
  **hard-hangs** on an otherwise healthy guest — the stack is blocked, not merely empty.
- Setting `GENERIC_GRAPHICS=on` restores a real emulated framebuffer: `vm-entry.sh` shows the
  headless mode is what rewrites `-vga vmware` to `-vga none`. The guest then has a genuine
  1920x1080 framebuffer (QEMU `screendump` returns 1920x1080 verbose-boot text instead of the
  640x384 EFI console), but it **freezes at ~0.145 s of boot**: WindowServer never composites to
  it, because `AMDRadeonX6000Framebuffer` claims the display role while exposing no connectors.

**That is the crux of this item:** with the iGPU passed through, Apple's AMD framebuffer takes
display duty and has none to give, and macOS will not fall back to the emulated framebuffer. The
two candidate routes were (a) stop the AMD framebuffer from claiming the display role so the
emulated framebuffer serves the desktop while the iGPU stays the Metal device, or (b) supply real
connectors by porting DCN 3.1.5.

### Route (a) is CLOSED — tested on hardware and refuted (candidate 1.0.231, card metal-079)

`mkrom.py --no-display-paths` does exactly what it promises, and it is still not enough:

| Observation | Connector ROM (baseline) | Zero-display-path ROM |
|---|---|---|
| `AmdRadeonFramebuffer` instances | 4, all "Driver is offline" | **0** (goal achieved) |
| `getConnectorTable` | populated | `ASSERT(0 != connectorCount)`, logs and continues |
| Console progress | freezes ~0.145 s | ~0.203 s, still never a login window |
| `AMDRadeonX6000` IOService nodes | present | present (4, plus 1 `IOAccelerator`) |
| `MTLCreateSystemDefaultDevice()` | device returned | **nil — "no Metal device"** |

Reproduced twice. **Suppressing the framebuffer costs Metal**: the accelerator kext still loads and
still registers IOService nodes, but macOS will not publish a GPU as a Metal device when it has no
display, so `AppleGPUWrangler` leaves it unusable. Metal does *not* come from the accelerator
alone, which refutes the assumption route (a) rested on. Reverting the ROM restored four
framebuffers and Metal device creation immediately.

**Only route (b) remains**: give Apple's framebuffer real, working connectors, which means porting
DCN 3.1.5 — `dccg2_get_dccg_ref_freq`, `hubbub2_get_dchub_ref_freq` and the `generic_reg_wait`
timeouts are where Apple's DCN 2.x/3.0 code gives up on this silicon. That is a large job.

**Delivery trap worth remembering:** Apple reads the VBIOS from the **`ATY,bin_image` device
property**, not from the file passed to QEMU with `--gpu-rom`. A rebuilt ROM does nothing until it
is injected into `config.plist` *and* the ESP copy inside `OpenCore.qcow2` is resynced; staging
refuses the mismatch with "raw ESP and config.plist preimage differ".

Today GPU passthrough runs `-display none`; the AMD scanout is unwired and `screendump` returns
only the EFI console. Give the guest a display surface that is actually presented, so the desktop
can be watched and captured without a remote-desktop codec in the path. This also removes the
main obstacle to item 1.

## 4. VirtualBox variant

Provide a VirtualBox-hosted configuration alongside QEMU/KVM, sharing the kext and the ROM
synthesis. Expected friction: PCI passthrough support, OVMF equivalence, and the option-ROM
64 KiB ceiling.

## 5. Production build without diagnostics

**Measured and confirmed on hardware (2026-09-14): the diagnostics make an interactive desktop
unusable, not merely noisy.** On a live desktop the kext emitted **~500 serial lines/second**
(3009 lines in 6 s). `debug=0x108` routes every `RLOG`/`SYSLOG` through `kprintf` to the emulated
16550 UART synchronously, so the kernel blocks on serial writes; on top of that
`wrapKiqSubmit` calls `kickKiq()` on every KIQ submit, which costs 8x`IODelay(500)` = 4 ms plus
~18 log lines each. The guest wedged: its command agent stopped answering and WindowServer's
display pipe stalled. Dropping `debug=0x108` and the dump flags (`rgpudump`, `rgpugolden`,
`rgpuhangdump`, `rgpuvmdiag`, `rgpusubmit`) while keeping every functional flag took serial to
**0 lines/6 s** and the guest booted responsive. The probe harness never saw this because it is a
short bounded workload.

Note a trap for the gating work: `kickKiq()` is gated on `mask & XK`, but `XK` is *functional*
("start the RLC microcontroller before the engines power up"), so the diagnostic cannot be
disabled by clearing that bit — it needs its own flag.

The kext currently carries extensive tracing (`rgpudump`, `rgpuhangdump`, `rgputilelog`,
`rgpuvmdiag`, submission tracing, replay). Gate all of it behind a build flag so a production
build contains only the corrections, reducing size, risk and serial noise.

## 6. Split `src/RaphaelGPU.cpp`

The file is ~8,500 lines and hard to navigate. Split by concern — ROM/ATOM, HWLibs dispatch,
SDMA/tiling, queues and submission, diagnostics, the userspace texture patch — keeping the
existing header split style and the regression suite green throughout.

## 7. HDMI audio sink

Investigate exposing the iGPU's HDMI audio function to the guest, if the display path in item 3
makes it meaningful.

## 10. Raise the guest display resolution — up to 8K 60 Hz

The default display tops out at 1080p (the current virtual display comes up at 1280×1024 /
1920×1080). The target is **up to 7680×4320 at 60 Hz**, which the Raphael iGPU's display engine
supports (the host already drives a Samsung panel at 3840×2160 and KDE has remembered 7680×2160 on
its DisplayPort). This depends on the display path: the virtual display's advertised modes (item 3)
must offer the high-resolution timings, and a physical scanout through DCN 3.1.5, if reached, must
drive the panel at that timing. Track EDID/mode advertisement, `CGDisplayMode` availability in the
guest, and the framebuffer's max stride/pixel-clock limits (8K60 is ~2 GHz pixel clock, ~127 MB per
BGRA8 frame).

## Host boundaries (unchanged, non-negotiable)

These are the rules that have kept the host alive; see [host-safety.md](host-safety.md).

- The iGPU must be initialised by `amdgpu` during the current boot before binding to vfio-pci.
  **Never cycle vfio-pci → amdgpu → vfio-pci within a boot.**
- Pin `power/control=on` before anything opens the device.
- The normal test path requires **no sudo**.
- Launch, serial capture and the stop deadline are owned by user systemd services; a GPU run
  requires a positive `RGPU_MAX_SECONDS`.
- No finite test can guarantee the host will never hang.
