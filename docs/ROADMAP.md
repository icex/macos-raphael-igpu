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

## 1. Diagnose the 8×8 block artifacts seen over remote desktop

Sparse 8×8-pixel blocks appear over translucent/vibrancy regions (Finder sidebar, Safari start
page, menu bar); opaque window interiors and bare wallpaper are clean.

The mechanism is **not** settled, and two candidates are still live:

- **A GPU/compositor defect** — 8×8 at 32 bpp is exactly one 256-byte GFX10 micro-tile, which
  would point at DCC/fast-clear metadata or a producer/consumer tiling disagreement on a
  screen-sized surface.
- **A remote-desktop codec artifact** — 8×8 is also the JPEG DCT block size, and every image we
  have is a host screenshot of a VNC/NoMachine client.

Ruled out already: a pipeBankXor displacement. With the kernel's chosen swizzle mode, pbx is
XORed *inside* a 64 KB block (128×128 px at 32 bpp), so it can displace by at most 128 px and
would permute *every* tile densely — the observed artifacts are sparse with content from far
away. The kernel additionally never computes pbx at all (no call sites to
`Addr2ComputePipeBankXor`), and `getIOSurfaceInfo` exports no pbx field.

**Discriminating test, in order:**

1. A **lossless in-guest capture** (`screencapture -x` from a GUI session, which is the only way
   to get the Screen Recording grant — SSH-launched processes never receive the prompt). If the
   blocks are absent, it is the transport and this item closes.
2. If present, a Metal probe that fills a screen-sized private render target with a poison
   pattern, releases it, re-allocates, draws known content, and consumes it via blit / sample /
   `optimizeContentsForCPUAccess` with `allowGPUOptimizedContents` YES vs NO. Blocks matching the
   poison ⇒ DCC/fast-clear; blocks matching same-surface content at a bounded offset ⇒ tiling.

`tools/vnc-frame-capture.py` and `tools/qemu-frame-capture.py` (restored from
`archive/desktop-195`) give a scripted capture path.

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

A read-only prototype and 11 passing structural checks already exist in
`findings/research/update-resilience-20260914/`. Scope: compatible updates within the same major
version. A major redesign of the settings constructor still needs maintenance.

## 3. Virtual display attached to the iGPU

Today GPU passthrough runs `-display none`; the AMD scanout is unwired and `screendump` returns
only the EFI console. Give the guest a display surface that is actually presented, so the desktop
can be watched and captured without a remote-desktop codec in the path. This also removes the
main obstacle to item 1.

## 4. VirtualBox variant

Provide a VirtualBox-hosted configuration alongside QEMU/KVM, sharing the kext and the ROM
synthesis. Expected friction: PCI passthrough support, OVMF equivalence, and the option-ROM
64 KiB ceiling.

## 5. Production build without diagnostics

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

## Host boundaries (unchanged, non-negotiable)

These are the rules that have kept the host alive; see [host-safety.md](host-safety.md).

- The iGPU must be initialised by `amdgpu` during the current boot before binding to vfio-pci.
  **Never cycle vfio-pci → amdgpu → vfio-pci within a boot.**
- Pin `power/control=on` before anything opens the device.
- The normal test path requires **no sudo**.
- Launch, serial capture and the stop deadline are owned by user systemd services; a GPU run
  requires a positive `RGPU_MAX_SECONDS`.
- No finite test can guarantee the host will never hang.
