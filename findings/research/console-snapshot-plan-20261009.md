# Candidate369: separate staging and acknowledged immutable host snapshots

Status: experimental patch drafts; no guest/native qualification. Candidate368
reported valid captured source tokens while the corresponding manager windows
contained invalid tokens. This motivates a downstream boundary experiment; it does
not identify QEMU as the sole fault or establish complete source pixel correctness.

## Ownership argument and deliberate limitation

The current bridge exports BAR0, also used by the firmware/boot framebuffer.
`IOService::open` excludes another bridge client, not the existing boot writer.
The opt-in QEMU property `x-debug-snapshot=on` therefore creates a distinct
32 MiB RAM MemoryRegion at BAR1. BAR0 is neither aliased nor copied into staging.
A new memory type1 exports only BAR1 to the staging owner; register MMIO remains
kernel-only. Existing memory type0 and selector0 retain their legacy interface.

One ARM is allowed per QEMU device lifetime, and one staging lease per bridge
service instance. Close or explicit DISARM retires the protocol permanently.
The bridge must not regrant the region merely because a user client closed:
its previous exported mapping could survive. QEMU's independent retired state
also refuses a new bridge instance. A presenter restart after ARM requires a new
VM/device for this diagnostic; this is not a production update/restart design.
An unsuccessful client startup before ARM does not consume the staging lease.

This excludes the identified BAR0 firmware writer by physical separation, and
old bridge owners by non-regrant. It is not protection against a malicious guest
kernel or a client sharing its own mapping with another task. The diagnostic
presenter is the sole cooperative staging writer, on its existing serial queue.
No claim is made that arbitrary third-party drivers never inspect PCI resources.

Pinned source: QEMU10.1.2 `hw/display/bochs-display.c` registers 32-bit BAR0 and
BAR2; `hw/pci/pci.c:pci_register_bar` consumes an adjacent register only for
MEM_TYPE_64, which is absent. BAR1 is free. SeaBIOS
`roms/seabios/vgasrc/bochsdisplay.c:bochs_display_setup` reads BAR0/BAR2.
OVMF `roms/edk2/OvmfPkg/QemuVideoDxe/Driver.c` uses BAR2 for Bochs MMIO and its
zero-initialized framebuffer BAR index0; only the separate VMware variant
changes that index to1. `Gop.c` publishes that framebuffer address. Native PCI
assignment of the additional32 MiB below4 GiB still requires verification.

## Register and guest API draft

BAR2+0x700, little-endian aligned32-bit transactions, size0x30:

| Offset | Direction | Meaning |
|---|---|---|
| 0x00 | R | capability/version magic0x52534731 |
| 0x04 | R | staging bytes33554432 |
| 0x08 | RW | state0 available, write1 ARM, write2 terminal DISARM |
| 0x0c | R | error0 success,1 state,2 register,3 sequence,4 geometry |
| 0x10/14 | RW | width/height |
| 0x18 | W | COMMIT sequence, strictly previousACK+1, starts1, no wrap |
| 0x1c | R | last successfully snapshotted sequence |
| 0x20 | R | last published sequence |
| 0x24 | R | replaced unpublished snapshot count |
| 0x28 | R | publication count |
| 0x2c | R | pending sequence,0 when absent |

Only packed little-endian32-bit xRGB,320x200 through3840x2160 is admitted.
3840x2160x4=33177600 bytes fits32 MiB; legacy4096x2304 does not.
The guest draft adds scalar selector1 ARM, selector2 `(w,h,seq)->ack`, selector3
DISARM. It validates exact argument shape, local-user/exclusive-client policy,
capability, BAR length, geometry, owner and ACK; no raw register export.

Presenter integration, deliberately not applied to the production presenter:
opt-in strict environment flag; ARM once, map memory type1 with existing WC
options, hold the readonly SCK sample while copying rows into packed staging,
SFENCE on that same worker, invoke selector2, require matching ACK before any
staging reuse. On error stop the experimental capture path and DISARM; never
fall back to BAR0 under an armed protocol. Unset flag remains existing path.
Geometry changes use the same packed staging region and increasing sequence.
Do not call legacy mode selector0 after ARM. Existing diagnostic source CRC
checks remain before the copy, and snapshot commit timing must be reported
separately from row-copy time. Kernel method does no polling: it performs a
synchronous MMIO write and immediate ACK readback. This does not bound a hung
emulator; the unchanged outer harness remains the hard runtime bound.

## Host publication lifetime

COMMIT's normal MMIO handler runs under QEMU BQL. Source corroboration:
`system/physmem.c:prepare_mmio_access` acquires BQL before MMIO dispatch.
`util/main-loop.c:os_host_main_loop_wait` reacquires BQL before GLib callbacks;
`main_loop_wait` then runs clock timers. `ui/console.c:gui_update` calls
`dpy_refresh`, whose SPICE callback invokes `graphic_hw_update`, hence the Bochs
refresh runs under BQL too. QMP screendump schedules the same update on the main
AioContext BH. No new thread or relaxed/global-locking override is introduced. It validates state/geometry,
allocates a new `qemu_create_displaysurface` with host-owned pixels, copies the
entire packed staging frame synchronously, installs that immutable pending
surface, then sets ACK. No deferred staging read is allowed. Guest SFENCE and
no staging reuse before ACK are essential; qtest cannot prove native WC ordering.

The existing display-refresh callback consumes the latest complete pending
surface, calls `dpy_gfx_replace_surface`, then full update. While armed it ignores
BAR0/VBE mode changes. A pending snapshot may be replaced before publication;
this is explicit frame dropping, not a FIFO or every-frame promise. DISARM frees
pending storage and returns the next refresh to legacy BAR0/VBE.

`ui/console.c` allocates owned pixman storage when create-displaysurface receives
no backing pointer. SPICE's `qemu_spice_display_switch` refs the new pixman image;
its update creation copies pixels to separately owned QXL update storage, freed
by resource release. Therefore guest staging reuse cannot mutate either host
snapshot. Never recycle published snapshot storage at ACK. Current, pending,
and in-progress copy require at most three full host snapshots at commit time;
SPICE's independently owned updates have their existing queue lifetime. Full4K
copy while holding BQL may add latency and memory bandwidth and must be measured.
Experimental snapshot state is not migrated: pre-save rejects the opt-in device.
Default device migration and property-off behavior are unchanged.

Immutable host storage does not make SPICE publication atomic. Existing SPICE
splits dirty regions into32-pixel-wide updates. The prior344 single-bounding-box
patch remains a separate diagnostic comparison, only after snapshot correctness
is established. Even one update does not prove host scanout or visual60 Hz.

## Minimum software qualification

`tools/qemu-snapshot-smoke.py` runs only paused TCG/qtest, no KVM or physical GPU.
It checks legacy pixels before ARM, commits and reads ACK, immediately overwrites
both staging and BAR0 and changes VBE, then verifies every QMP screenshot pixel
still equals the acknowledged snapshot. Cases cover640x480,1920x1080,3840x2160,
resize800x600, repeated immutable screenshot, two pending frames/latest wins,
invalid geometry and duplicate sequence rejection, DISARM legacy return and
re-ARM refusal. Retain argv, binary hash, full PPMs, result and QEMU exit status.
Run the existing legacy smoke with the same binary and no new property to check
unchanged default. This is a serialized software boundary proof; it does not
qualify native mappings/fences, capture integration, SPICE client or acceleration.

Then compare snapshot-only and snapshot plus single-bbox using an atomic qtest
producer with source IDs and the same manager token decoder. Retain invalid
categories and all raw samples. Native testing requires parent review, a separately
pinned image and manifest/argv admission, compiled guest patch and presenter,
normal consent handling, exact BAR length/assignment receipts and supervised run.
