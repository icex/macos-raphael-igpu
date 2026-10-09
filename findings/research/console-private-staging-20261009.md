# Private snapshot staging — candidate394 preparation

Implementation compiled; native behavior remains unqualified before the run.
The signed capture app and presenter ABI1 are unchanged. The external launcher
selects snapshots only when both SnapshotRestartable and SnapshotProtocol equal1,
sets default cache explicitly, and does not retry or fall back after presenter failure.
Legacy hosts still select ordinary capture in the installed launcher.

The bridge now exports fresh zeroed32MiB RAM per successful owner through type1,
never BAR1. Its kernel-only WC BAR1 mapping receives a serialized copy, followed by
SFENCE and host COMMIT. Exact ACK and active epoch are checked. The driver retires
and permanently poisons the service snapshot path after ambiguous host completion.
The old host retains one-shot admission; the new magic uses explicit epochs.
Each client connection may ARM once, including ambiguous attempts. Close marks a
connection retired even if a concurrent ARM is still allocating. Type1 retain,
commit, close and stop serialize through the provider lock.

A descriptor subclass reserves one of four global live-buffer slots before
allocation. Its free override returns the slot only after superclass free has
released the backing memory, using saved stack data and a global counter afterward.
Retained mappings therefore retain their slot; client close does not replenish it.
The payload bound is128MiB, excluding object overhead. Eight open connections are
allowed through IOService arbitration to permit retained retired owners; there is
still exactly one publishing owner. Allocation failure refuses ARM.

The descriptor rejects every mapping cache flag except default/copyback before
compatible-map lookup. Setting clientMemoryForType options alone is insufficient:
IOUserClient merges user map flags over the cache bits. Rejection follows the
x86_64 makeMapping incoming-IOMemoryMap ownership convention. This is a native ABI
qualification requirement, not proof derived from compilation.

Source audit: local pinned MacKernelSDK IOBufferMemoryDescriptor.h public
initWithPhysicalMask and virtual free, IOMemoryDescriptor.h virtual makeMapping,
IOService.h arbitration hooks, and current Apple upstream sources:

- https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/Kernel/IOMemoryDescriptor.cpp
- https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/Kernel/IOBufferMemoryDescriptor.cpp
- https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/Kernel/IOUserClient.cpp

Current upstream is not a pinned24G830 implementation audit. Native alias refusal,
retained-map lifetime, capacity recovery, owner death and concurrent close/commit
remain required. tests/console_snapshot_restart.c checks old-owner writes and calls,
fresh zeroing, cache rejection, full-frame ACK, four retained mappings and capacity
recovery. Host full-pixel comparison must independently verify the published image;
the native fixture's private-buffer readback and ACK are not manager-delivery proof.

The extra kernel copy moves33,177,600 payload bytes for4K and its real cost remains
unmeasured. Existing presenter timing includes synchronous commit cost. Default
ordinary capture, driver acceleration and host recovery stay separate outcomes.
