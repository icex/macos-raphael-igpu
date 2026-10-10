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

## Candidate438 hardware outcome: no compression activation

683a808b91d8c4fa8655e0b3f6077eea/metal232, build4de0edff55ad4cdb9543eeac776c0f96,
MODE2333. CORE_PROBE_PASS, unchanged GPU source. ExplicitOFF A actual scale2
4K Retina60, full-field client22.89/22.75 versus server45.79/45.51 commands/s;
localized55.83–56.30.38startup-invalid,0post-start,1duplicate. Traced-run rates,
not GPUFPS/full-frame validation. No queue-busy skips, raw control reproduces437.

B viewport drifted1440×900→2160×1381 fourseconds after readiness. Observer
sampler-error before any valid token; excluded. Stop owned viewer and fixture.
Do not classify missing tokens as codec corruption: QEMU /proc environment
shows the activation flag MISSING; libvirt sanitizes inherited image environment.
The new library was mapped, but compression opt-in was never active. Raw-channel
traffic therefore is not an exercised-codec result. Static pixel fixture prepared
but not run. Artifacts c438-qemu-spice-runtime-env.json and cadence summary retain
these distinctions. Next research gate will use explicit negotiated clientLZ4
preference itself, preserving defaultOFF and other Unix codecs' raw behavior;
there is no need for broader environment inheritance or safety-gate changes.

25 upstream tests each baseline/modified,1550 hosttests8skip before438. Normal
guest-requested exit and natural captures/private terminal verified, with stopped
container inspection reconciliation unavailable/mismatched. Recoveryauthorizes
reuse. All branches remain research-only. No60fps or delivery milestone claimed.
