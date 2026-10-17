# VirtualBox presentation transport: next implementation boundary

Read-only source audit in candidate405, based on fetched dev84159a9. No build,
VM/device access, guest command, host change or deployment. The root's candidate403
software-desktop result does not establish Raphael acceleration or a presentation
adapter. This report proposes work; it implements none.

## Exact mismatch

The audited VirtualBox release is7.2.18, commit
`14841851fa211c7faf615978ba385d59947236c6`. Sources and SHA256 are retained under
`run/c405-vbox-display-source` and the companion source-pin JSON. DevVGA.cpp matches
the prior audit's SHA256131c03acd816f193b6d62844a788fd58ae16df06801f22e9286419b9a1af5972.

| Contract | Existing Raphael bridge | Stock legacy VBoxVGA |
|---|---|---|
| PCI identity |1234:1111, class038000 |80ee:beef, class030000 |
| Pixels | BAR0,16–64MiB | BAR0 dirty-tracked VRAM, configured size |
| Mode registers | BAR2+0x500,4KiB BAR | Indexed I/O ports0x1ce/0x1cf |
| Immutable staging | Dedicated BAR1,32MiB | No equivalent in inspected legacy path |
| Publication | Epoch/sequence/ACK at BAR2+0x700 | Mutable VRAM scanout and update notifications |

VBoxVGA's region layout and construction are in DevVGA.cpp6777–6805,
6815–6849,6950–6985. The VMSVGA/VBoxSVGA configurations have other layouts and must
not inherit this match. Register writes recalculate stride/start offset
(940–969,1168–1177). They do not confer lifetime ownership of a completed image.
Graphic resize passes a VRAM pointer to the display connector (2184–2220).
[Release DevVGA.cpp](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Devices/Graphics/DevVGA.cpp).

DisplayImpl retains/queryable source-bitmap state, can notify a framebuffer by
rectangle, or copy pixels into an update-image array. A pointer or mode change is
not an acknowledgement that all consumers released the preceding image.
See DisplayImpl.cpp740–806,905–1003. No audited completion contract connects those
consumer lifetimes to a guest bank-reuse decision.
[Release DisplayImpl.cpp](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Main/src-client/DisplayImpl.cpp).

## Smallest useful guest slice, and its limit

A separately opted-in VBox backend can reuse the sealed presenter's existing
selector0 and memory-type0 ABI for a **non-atomic** scanout experiment: exact
VBoxVGA identity, BAR-size/pitch bounds, serialized indexed-port access, readback,
and a backend-specific stop path. It must advertise SnapshotProtocol=0. Do not
fabricate selector2 ACK by returning after a memcpy into scanout VRAM. Never
share the Bochs BAR2 map or shutdown write with this backend.

Before enabling any writes, qualify which service owns the boot framebuffer and
how it relinquishes mode/VRAM publication. Existing ConsoleBridge start/stop has
no arbitration with an EFI/macOS framebuffer writer. The virtual-display holder
mirroring other displays does not itself remove that writer. A match-only patch
would leave both stale mapping and concurrent publication risks unresolved.
Thus the immediate implementation unit should separate backend discovery and
register operations from publication policy, with writes disabled until an
explicit ownership handoff is established; root can then qualify a bounded static
pattern and restoration on the software-only clone. It is transport groundwork,
not the requested finished accelerated desktop.

## Production atomic path

The existing sealed presenter can stay unchanged if a VBox backend preserves its
private per-client staging, exact selector/ACK behavior and retired-mapping rules.
A scoped host extension could consume a completed guest staging bank synchronously,
copy it to host-owned immutable storage before ACK, and transfer that storage to
VBox display consumers with explicit release ownership. It needs epoch/retire,
geometry, delayed-consumer and device-destruction tests equivalent to QEMU; adding
only new registers is insufficient. Prefer a separate opt-in device contract over
silently reinterpreting normal VBoxVGA VRAM.

This audit does **not** prove a host patch is universally necessary. Stock
HGSMI/VBVA declares flush, screen and completion mechanisms (VBoxVideo.h345–378,
479–540), but those names alone do not establish immutable pixel lifetime.
An existing VMSVGA surface/fence path may offer a guest-only implementation;
its host and consumer ownership needs a separate narrow audit before choosing it.
[Release protocol declarations](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/include/VBox/Graphics/VBoxVideo.h).

GPU compatibility remains independent: the prior ID/ROM audit still applies.
Presentation groundwork does not qualify real164e matching, native VFIO ROM,
DMA/reset safety or accelerated WindowServer use under VirtualBox.
