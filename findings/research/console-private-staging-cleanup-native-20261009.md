# Candidate395: retired private-map cleanup and capacity recovery

**Native ownership fixture passes; performance and final lifecycle pending.**
Run`074a0b4c757c6c21ae093b604a98763d`. This extends394's positive pixel-isolation
result and fixes its explicit retired-unmap failure; it does not reclassify394's
failed cleanup or forced VM teardown. Root owns all native operations.

395 retains a per-client private descriptor through RETIRE. IOKit's unmap lookup
can therefore recover that same descriptor; the active provider owner remains
the only connection allowed to publish. A retired client may remap its own old
RAM, never the new owner's backing. Final close drops its descriptor reference;
retained mappings still determine actual lifetime and the four-buffer limit.

## Completed native fixture

`c395-native-final.txt` reports`passed:true`, `step:complete`,
`cleanup_ok:true`, process exit0. Old COMMIT/re-ARM and WC alias requests remain
refused. Retired A's explicit unmap returns0, remapping its own RAM matches with
zero mismatches, and every recorded final retire/unmap/close returns0.

Four retired retained buffers exhaust the slot pool. After explicit A unmap and
connection close, a fresh owner successfully arms and maps fresh zeroed storage.
This is the concrete capacity-recovery regression that failed in394.

B publishes a known801×601 frame with ACK1. Independent QEMU screenshots before
and after poisoning retained A's private mapping each match all481401 pixels,
zero mismatches. No new B commit occurs between the windows. This demonstrates
that retired-writer isolation through the host snapshot survives the supported
unmap/remap lifecycle. It is not full dynamic manager-frame qualification or a
proof against a current owner writing concurrently with its own commit.

Installed helpers automatically start snapshot capture; after the native fixture,
normal installed capture is restored. The source/manager performance window is
currently active and is intentionally excluded from this revision's artifact
hashes. No cadence or final shutdown conclusion is made yet.

## Remaining qualification

Pending: completed mixed-motion observations and source/copy timing, final actual
manager desktop, audio/restoration and capture/private-terminal/Docker/recovery
receipts. The earlier capture-abort race is independent of this ownership fix.
Client death during commit, broader restart stress and independent host-boot
coverage remain open. GPU-native virtual transport and VirtualBox remain
unimplemented; neither ACK nor token samples are physical scanout FPS.
