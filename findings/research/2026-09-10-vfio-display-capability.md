# VFIO passthrough display capability review

This is a read-only offline review. No VM, QEMU device, VFIO group, PCI sysfs
node, sudo command, generic adapter, or GPU launch was used.

The pinned QEMU 10.1.2 binary in the existing Docker image reports this
`vfio-pci` option:

```text
display=<OnOffAuto> - Enable display support for device, ex. vGPU (default: off)
x-vga=<bool>       - Expose VGA address spaces for device (default: off)
```

QEMU's display backends include `none`, `gtk`, `sdl`, `egl-headless`, `curses`,
`spice-app`, and `dbus`. The device list includes `ramfb`, `VGA`, and
`vmware-svga`, but these are separate display devices. `ramfb` is a system RAM
framebuffer for firmware/early output; it does not turn a physical VFIO GPU
into a GTK scanout device.

The current launcher builds the passthrough argument as:

```text
-device vfio-pci,host=0000:7b:00.0,bus=pcie.0,
  x-pci-vendor-id=0x1002,x-pci-device-id=0x73ff,romfile=/run/vm/gpu.rom
...
-vga vmware
-display gtk,gl=on
```

Thus the GTK window is backed by QEMU's emulated VMware adapter. The passed
through Raphael function has no `display=on` or `x-vga=on` property. QEMU's
VFIO display implementation probes the assigned VFIO file with
`VFIO_DEVICE_QUERY_GFX_PLANE` for a DMABUF or display-region plane and maps a
successful plane into a QEMU display surface; in automatic mode, neither known
method leaves the VFIO device without a display surface. See the [QEMU
v10.1.2 VFIO display probe](https://raw.githubusercontent.com/qemu/qemu/v10.1.2/hw/vfio/display.c#L478-L543).
This is a capability-query path, not an automatic physical connector/scanout
bridge. No such query was run against Raphael here. `-vga none`
would remove the emulated VMware framebuffer; `-display gtk` would then have
no normal guest framebuffer to show. Adding `ramfb` would only add a software
RAM framebuffer and would violate the requested no-generic-adapter intent.

The repository's prior evidence agrees. The VM README records that the guest
display remains on the emulated VMware adapter and that the passed through
iGPU produced no framebuffer. `findings/GPU-RE.md` records that the iGPU's
DCN 3.1.5 display implementation is absent from Apple's driver resource pool,
and that the guest driver never reached framebuffer initialization. The same
report also documents why the GPU remains directly on `pcie.0`; a root-port
topology caused macOS to unmap all GPU BARs.

## Answer to the requested GUI mode

With the current QEMU and current macOS/Raphael software path, no GTK window
showing actual Raphael scanout has an implemented or verified route. Changing
`-vga` alone does not establish one. QEMU's VFIO display support requires the
assigned device to answer the graphics-plane query above; this review did not
query the live device, so it does not claim every physical VFIO GPU can never
expose a display surface. A real accelerated desktop would require the guest
driver to initialize a usable display engine and a separate scanout transport
(or a supported mediated-vGPU implementation); current evidence says the
Raphael DCN path is blocked before that point.

Therefore the explicitly requested “start QEMU again with the passed-through
Raphael display and no generic adapter” has no implemented/verified route under
the current evidence and should remain gated. The existing GTK window can
display the emulated VMware framebuffer, while Raphael passthrough can only be
evaluated as a compute/driver experiment under the project's hardware gates.
The user's prohibition on a generic GPU adapter is recorded for future work;
no such adapter should be introduced to manufacture GUI output.
