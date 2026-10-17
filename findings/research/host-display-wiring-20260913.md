# Host GPU and display wiring (2026-09-13, boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`)

Read-only inventory from sysfs, `lspci`, `loginctl`, `kscreen-doctor`, the KDE output
configuration, and the current kernel journal. Nothing was changed.

## GPUs

| Function | Device | Driver | DRM | Role |
|---|---|---|---|---|
| `0000:03:00.0` | Navi 48 RX 9070 XT `1002:7550`, Sapphire `1da2:e489` | `amdgpu` | `card1` | `boot_vga=1`, primary; BAR0 16 GiB at `0xf800000000` |
| `0000:03:00.1` | Navi 48 HDMI/DP audio `1002:ab40` | `snd_hda_intel` | | IOMMU group 16 |
| `0000:7b:00.0` | Granite Ridge (Raphael) iGPU `1002:13c0` rev cb, MSI `1462:7e59` | `amdgpu` | `card0` | `boot_vga=0`; BAR0 256 MiB at `0xfc20000000`, BAR2 2 MiB `0xdd400000`, BAR4 I/O `0xd000`, BAR5 512 KiB `0xdd900000`; VBIOS `102-RAPHAEL-008`; VRAM 512 MiB, GART 1 GiB, PSP TMR `0xa00000` at `0xf41e000000`; `reset_method=bus`, `power/control=on`, `runtime_status=active` |

Bus 7b sibling functions, each in its own IOMMU group and all host-owned: `.1` Radeon HD
audio (group 32, `snd_hda_intel`), `.2` PSP/CCP `1022:1649` (33, `ccp`), `.3` and `.4`
xHCI `1022:15b6/15b7` (34/35, `xhci_hcd`), `.6` Ryzen HD audio `1022:15e3` (36, no
driver). The iGPU is alone in IOMMU group 31, which is what VFIO needs, but the shared bus
is why no bus reset is ever possible while the siblings stay on host drivers.

Kernel command line: `amdgpu.runpm=0 drm.edid_firmware=HDMI-A-1:edid/sunshine-virtual.bin
video=HDMI-A-1:e nmi_watchdog=1 hardlockup_panic=1 efi_pstore.pstore_disable=0 panic=20`.
Udev rule `/etc/udev/rules.d/99-vfio-igpu-nopm.rules` pins `power/control=on` for
`1002:13c0`. No `modprobe.d` entries for vfio or amdgpu.

## Connectors and the monitor

| Connector | Card | Status | Sink |
|---|---|---|---|
| `card0-HDMI-A-3` | Raphael iGPU | connected, enabled, DPMS on | Samsung Odyssey G95NC (EDID vendor SAM, product 29654, serial 810635354, week 40 2023; 256-byte EDID, preferred 3840x2160@60; modes down to 640x480) |
| `card0-DP-3`, `DP-4`, `DP-5` | Raphael iGPU | disconnected | |
| `card1-HDMI-A-1` | RX 9070 XT | connected, enabled | forced virtual EDID `sunshine-virtual.bin` (LNX 1920x1080@60) for Sunshine streaming; Sunshine captures this output |
| `card1-DP-1`, `DP-2`, `HDMI-A-2` | RX 9070 XT | disconnected | KDE remembers the same Samsung monitor on `DP-2` (3840x2160@120) and `DP-3` (7680x2160@240), so the monitor's DisplayPort input is cabled to the dGPU but not active now |

The physical monitor is therefore reachable right now only through the iGPU's HDMI port.
The KDE Plasma 6 Wayland session (`kwin_wayland`, seat0, tty2) has two enabled outputs:
`HDMI-A-1` (virtual, priority 1, 1920x1080 at 0,0) and `HDMI-A-3` (Samsung, priority 2,
3840x2160@60, scale 1.5, geometry 1920,0). The compositor reports HDMI-A-3 as enabled and
on, so the iGPU is currently driving the desktop image on the Samsung; it is not disabled at
the DRM or compositor level. The iGPU's display controller logged `REG_WAIT timeout ...
optc31_disable_crtc` at boot, the same DCN 3.1.5 warning seen on earlier boots.

## Consequences for the VM work

- Binding the iGPU to `vfio-pci` takes the Samsung's only active input away from the host
  desktop; the host session then lives on the Sunshine virtual output alone. For a
  physical-display test in the guest, the HDMI cable to the iGPU is the path macOS would
  drive through DCN 3.1.5, and the EDID recorded above is the sink it will see.
- `7b:00.1` (the iGPU's HDMI audio) is on `snd_hda_intel` and in a separate IOMMU group;
  it is not passed through, so guest HDMI audio is not available and the function stays
  host-owned.
- The iGPU's `bus` reset method is advertised but unusable (multifunction device, siblings
  on host drivers), and the `pm` method is disabled by the kernel's ATI quirk, so the only
  reset the device ever gets is amdgpu's own MODE2 at unbind.
