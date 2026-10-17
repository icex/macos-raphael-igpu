# IH DMA lifetime repair

The observed failure is an interrupt ring still writing after its QEMU owner
has exited. With the host's identity default IOMMU domain, subsequent writes
can reach host allocations. Existing PCI bus-master and GC/SDMA recovery
checks did not detect it. Evidence and remaining attribution limits are in
`findings/research/guest-memory-corruption-20261015.md`.

The repair has three boundaries:

1. QEMU disables all three OSSSYS 5 IH rings, ring-zero pointer writeback and
   interrupts, and self-interrupt pointer forcing before releasing mappings.
   This uses host-known offsets independently of guest display initialization.
2. An independently supervised host guard receives a duplicate VFIO device
   descriptor before guest execution. Linux's device descriptor retains the
   group/container and DMA mappings if QEMU or its whole container dies. The
   guard disables IH and the existing display write sources, then halts the
   measured GC/SDMA producers and checks their idle state before releasing
   ownership. Failure retains the descriptor and blocks another launch.
3. Recovery and admission require disabled IH controls and stationary hardware
   pointers sampled over time. Old receipts without this evidence cannot
   authorize another launch under the repaired helpers.

No binding, host KVM setting, default IOMMU policy or GPU firmware is changed.
Normal shutdown, monitor closure, forced container stop and QEMU process death
must each be exercised, with post-exit IH samples and independent guest/host
integrity checks. A successful software test or reset ACK is insufficient.

Implementation and hardware qualification are in progress; this document is
not a recovery receipt or a claim that the repair has passed qualification.

## Implementation and provenance

`tools/ih_dma.py` uses source-backed OSSSYS 5 masks and requires five samples
at least 25 ms apart. It clears only ring enables, IH0 interrupt/writeback
enables and self-interrupt pointer forcing. It never rewrites target addresses
or pointers. `tools/ih-vfio-recover.py` adds schema-10 normal receipts around
the sealed schema-6 GC/SDMA/PSP producer. Historical schema-6 verification is
preserved; a repaired launch requires schema 9 with IH evidence or schema 10.

The QEMU patch is `patches/qemu/10.1.2-vfio-rgpu-dma-guard.patch`, applied after
the existing v18 patches. Its isolated build tree is
`~/macos-vm/run/c515-qemu-runtime`. The local QEMU baseline commit
`08325543f` snapshots the complete pre-existing runtime v18 source, including
its audio patch; the new diff changes only VFIO files. Pins v19 identify the
resulting image. The `x-rgpu-dma-guard=on` property makes older images refuse
the repaired launcher before realizing its VFIO device.

The normal stop callback runs at `RUN_STATE_SHUTDOWN`, after `pause_all_vcpus`
and before QEMU cleanup can remove RAM mappings. Device exit and display
region finalization also call the guard. On abrupt death, the independent host
unit observes the QEMU pidfd while retaining its SCM_RIGHTS device descriptor.
Linux `vfio_group_use_container` retains the group file for device fds;
`vfio_group_fops_release` detaches only after device references are gone.
The legacy type1 backend retains its pinned DMA pages until unmap/release.

The later GTK auto-fit/host-cursor patch and v20 QEMU image retain the v19
guard sources and `x-rgpu-dma-guard=on` launch contract. Their separate source
and image provenance is recorded in
[the display helper documentation](igpu-display-helper.md#qemu-v20-window-fit-and-cursor).
These source paths were inspected at Linux revision
`238650ef6c7c7cca08e032527329424c9fbd70e5`; see also the
[VFIO interface documentation](https://docs.kernel.org/driver-api/vfio.html).

The guard is a separate user service with no forced stop timeout. Cleanup
failures retain its descriptor and block reuse. Its receipt is separate from
the full GPU recovery receipt and never authorizes a launch itself. Killing
this independent owner while it retains an unquiesced device is outside the
qualified shutdown paths.

`tools/install-ih-dma-guard.py` backs up replaced helpers, checks the known
supervisor preimage and applies two small launcher insertions. This preserves
the live launcher's local CPUID configuration. Desktop installation for 515+
uses the same installer before changing the release selection.


## GC/SDMA release boundary

The first guard revision stopped IH/display writes but left GC and most SDMA
inputs to the later recovery. In the SIGKILL run's later recovery, CP ME was
unhalted, five HQDs were active, and SDMA GFX/PAGE inputs remained enabled.
Their observed state does not prove DMA occurred in that interval, and the
subsequent plain-guest panic remains unexplained. It exposes a release boundary
that must be closed independently of attributing that panic.

`tools/dma_engines.py` now closes measured SDMA GFX/PAGE/RLC0/RLC1 inputs,
disables automatic context switching and halts SDMA F32. It disables CP pointer
polling/doorbell ingress and halts graphics/compute command processors. These
are existing sealed recovery offsets/masks and Linux `gfx_v10_0_cp_*_enable` /
`sdma_v5_2_enable` operations; Linux's GC idle test supplies GRBM GUI_ACTIVE.
The guard requires CP_STAT/CPC_BUSY zero, GUI_ACTIVE clear, SDMA idle, and all
halt/input controls proved over five timed samples before SAFE/release. Busy or
inaccessible registers retain the descriptor; no reset or ring-target change is
attempted. Full scheduler/PSP retirement remains in the separate recovery.

Schema-2 guard receipts bind this extra helper and proof. Prior schema-1 runs
remain historical IH containment evidence and do not qualify this stronger
release boundary. This covers the measured engines; it is not proof about every
possible autonomous GPU DMA source. Native and abrupt paths must be repeated.
