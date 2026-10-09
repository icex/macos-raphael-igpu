# VirtualBox7.2.18: backend presence is not Raphael qualification

Read-only audit; no VirtualBox VM was created/started and no VFIO/device descriptor
was opened. The companion Python script only checks filesystem metadata and emits
a proposed configuration. Current QEMU native ownership remains with root.

## Exact release boundary

Official tag`v7.2.18` resolves to commit
`14841851fa211c7faf615978ba385d59947236c6`; the companion source-pin manifest hashes
six primary source files at that commit. Installed`VBoxManage --version` reports
7.2.18r175117. Read-only strings in installed`/usr/lib/virtualbox/VBoxDD.so` include
`pci-vfio`, VFIO paths and backend diagnostic text. This contradicts a blanket
assumption that current VirtualBox contains no Linux passthrough implementation.

`Config.kmk` enables`VBOX_WITH_VFIO_PCI_PASSTHROUGH` on Linux;
`Devices/Makefile.kmk` builds`Bus/DevPciVfio.cpp`. That backend contains BAR/ROM/VGA,
DMA mapping, MSI/MSI-X and device-reset handling. However release
`ConsoleImplConfigX86.cpp` still guards the ordinary assignment path with the old
`VBOX_WITH_PCI_PASSTHROUGH`, selects`pciraw`, and contains the old extension-pack
check. Current master instead integrates`pci-vfio` there. Backend presence alone
therefore does not prove that release VBoxManage PCI assignment reaches it.

## Smallest proposed runtime discriminator

Use a separately owned diskless throwaway VM, no real PCI attachment. Apply the
companion script's exact CFGM overlay through the supported`VBoxInternal/` extra
data parser (`ConsoleImplConfigCommon.cpp`, overlay/type parsing). The script
never applies it or starts a VM. Before eventual root execution, recheck that
`/sys/bus/pci/devices/ffff:ff:1f.7` is absent and `/dev/null` is the expected owned
character node. Both IommuPath and VfioPath point **below** `/dev/null`, a
non-directory, so pathname resolution must fail ENOTDIR before opening an IOMMU
or VFIO container. A nonexistent HostAddress alone is insufficient: release
`pciVfioConfigureAccess` opens IOMMU/container paths first (lines2422–2446).

Expected positive discriminator: device construction reaches the exact
`Opening VFIO container path ... failed` diagnostic for the guarded fake path.
Retain independent syscall evidence of the two failed path attempts and no actual
`/dev/vfio/*` or`/dev/iommu` access. Missing device registration or an earlier CFGM
error is a failed discriminator, not a backend pass. Normal VM CPU/module setup
could fail earlier; this requires no bypass. Runtime launch/cleanup is root-owned
and still pending. This proves only configuration dispatch, never safe passthrough.

Before Raphael exposure, audit actual DMA/IOMMU ownership, implicit reset calls,
MSI routing and required PCI identity/ROM handling. The release device reset path
issues`VFIO_DEVICE_RESET`; this audit found no reviewed switch implementing our
existing reset/host-recovery policy. Existing QEMU admission cannot be borrowed
for an unrelated hypervisor process.

## Smallest presentation adaptation

The current bridge requires Bochs ID1234:1111, class038000, BAR2 MMIO VBE at0x500,
and optional private snapshot BAR1/doorbell0x700. Release`DevVGA.cpp`'s legacy
VBoxVGA path instead uses80ee:beef/class030000, VBE port I/O0x1ce/0x1cf and its own
VRAM region. Merely changing the PCI match would access the wrong contract.
VMSVGA uses another register/FIFO path; its3D host backend is not a macOS Metal
user/kernel driver.

Smallest presentation-only code slice, after a separate software VirtualBox
baseline: add a distinct VBoxVGA transport implementation selected by exact device
identity, bounded VRAM and explicit VBE I/O access, then a known-pixel/resize/readback
probe in the actual VBox console. Preserve the current QEMU bridge. This provides
pixels only; full acceleration still requires safe Raphael passthrough or a new
macOS virtual-GPU driver. The existing immutable QEMU snapshot protocol would
also need a VBox device extension or another independently qualified publication
mechanism; ordinary VRAM writes are not restart-safe atomic publication.

A VirtualBox-styled viewer around QEMU would not satisfy the requested actual
VirtualBox hypervisor support. Both rendering access and its own display/input/
audio/lifecycle must be qualified; no configuration-only success is claimed here.

## Executed software discriminator (root-owned)

Root executes the guarded configuration on installed7.2.18. Untraced startup
reaches the exact backend error: opening`/dev/null/raphael-discriminator-vfio`
fails with20 (`VERR_PATH_NOT_FOUND`). Retained`VBox.log` contains the actual CFGM
values. This establishes installed backend configuration dispatch; the VM never
boots. Machine state is verified poweroff, then the owned VM is unregistered,
with files retained in`run/c396-vbox-dispatch` and pinned by the accompanying
13-artifact evidence manifest. The wrapper's exit-untraced.json returncode0 is
not guest success: the retained application log explicitly reports startup failure.

The attempted traced start fails earlier in VirtualBox hardening with effective
UID not root, consistent with the setuid tracing restriction. Consequently there
is **no successful syscall-trace proof** of the untraced startup. The retained
`opens.strace` covers only that failed traced attempt. The fake access paths and
exact ENOTDIR diagnostic support the configured refusal; do not promote this to
independent traced proof that all actual device opens were absent.

No Raphael attachment, PCI enumeration, DMA, interrupts, reset, macOS boot,
Metal acceleration or VirtualBox console adaptation is qualified by this result.
The earlier proposed acceptance included a syscall trace which remains unfulfilled;
its absence is recorded, not silently replaced by the configuration result.
