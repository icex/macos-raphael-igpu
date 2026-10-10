# Candidate438: native Unix SPICE lossless compression experiment

Only full-field4K console performance is active. Keep host viewer normal1440×900,
GDK1, no automatic input grab/USB redirection. Hold other roadmap work.

437 traced Retina60 exposed a server→viewer gap:45-ish creation/dequeue vs23-ish
client decoded IDs/s. Client LZ4 preference alone did not help: raw747–758MB/s,
and matching-version dcc-send.cpp bypasses all compression for AF_UNIX.

Image derives from437 QEMU pipeline timing image. Only SPICE library rebuilt,
matching upstream0.16.0 archive, baseline and opt-in have identical121 exports.
Compile with container dependencies, SASL/Opus/LZ4 enabled, GStreamer off,
smartcard disabled. Both baseline and modified25 upstream tests passed. Runtime
image enables RGPU_SPICE_UNIX_LOSSLESS=1; Unix only admits requested LZ4, all
other preferences retain raw. Non-Unix behavior unchanged. LZ fallback remains
lossless. Default mode off. Guest firmware and capture app unchanged.

The compiled policy test validates null/empty/wrong flags and every codec versus
Unix/TCP. This does not prove client rendering or image integrity. Next runtime:
explicitOFF thenLZ4 with same viewer/workload/trace configuration and actual
source geometry. Measure channel bytes to distinguish request from actual effect;
count tokens separately from full pixels. Follow with deterministic static
full-pixel equality if speed improves; then repeat/revert to check host-load drift.
Keep server dequeue distinct from client delivery. Do not claim60fps from60Hz.

Provenance ~/macos-vm/run/c438-spice-build-provenance.json; build logs and upstream
results retained. Source setup overrides missing packaged glib-mkenums with pinned
retained generator; no runtime source change beyond reviewed opt-in patch.
No hardware result yet; source GPU d1deade... preserved. No feature publication.
