# Candidate395: retired private-map cleanup and capacity recovery

**Native ownership fixture passes; mixed-motion observations complete; final lifecycle pending.**
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
normal installed capture is restored. Completed source/manager observations are retained below. Final shutdown remains
pending and is not inferred from functional success.

## Installed mixed-motion observations

Two110-second source fixtures alternate localized and smoothly changing full-field
phases; each actual-manager ROI/event observation runs100 seconds. At matched
1440×9001×,5793 unique IDs over100.011s give57.924 observed IDs/s. The first five
phases individually span57.85–58.03 observed unique intervals/s. At4K,4041 unique
IDs over100.013s give40.405/s overall; localized phases span49.66–50.24/s and the
two complete full-field phases25.95–26.21/s. Source draw intervals are about60/s.
The final short source phase is not a complete observed phase.

All11 native-size and10 4K invalid observations precede the first valid token;
zero post-start token errors occur in either window. Maximum observed token-change
gaps are34.31ms and66.69ms respectively. The observer itself runs synchronously
and can slow decoding; region callbacks are not frames or scanout. No source CRC
qualification or absolute cross-clock latency measurement is claimed here.
The unchanged capture app remains installed. Root views the final actual-manager
`c395-post-motion-desktop.png` as a correct normal desktop.

This demonstrates sustained bounded token delivery under the installed immutable
path, not full-frame dynamic integrity, GPU FPS or universal60Hz. Prior ordinary
presentation results are not a matched full4K control, so these observations do
not establish a regression or isolate the added kernel copy as the bottleneck.

## Remaining qualification

Final audio/restoration and capture/private-terminal/Docker/recovery receipts are
pending. The earlier capture-abort race is independent of this ownership fix.
Client death during commit, broader restart stress and independent host-boot
coverage remain open. GPU-native virtual transport and VirtualBox remain
unqualified; neither ACK nor token samples are physical scanout FPS.
