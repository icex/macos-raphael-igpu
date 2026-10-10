# Candidate439: explicit client request activates Unix lossless encoding

438's image environment flag never reached QEMU because libvirt sanitizes it;
no compression was exercised. This patch uses the client's explicit LZ4 request
as opt-in. Default/OFF and every other Unix preference retain raw; TCP unchanged.
No broad environment inheritance, launch-authority or host-safety change.
The predicate reads the effective server-side LZ4 setting, not request provenance.
Under our pinned image-compression=off server configuration, activating LZ4
requires client negotiation; server-configured LZ4 elsewhere would also activate it.

QEMU437 unchanged, matchingSPICE0.16.0 library rebuilt with same options as438,
121 matching exports,25 upstream tests passed. Exact policy compiled/tested for
all codec values and families. Existing lossless LZ/raw fallback and compressed
buffer lifetime retained. This source control does not prove runtime integrity.

Target: actual1920×1080logical/3840×2160backing scale2 source60, normal fixed
1440×900/GDK1 host window, no input grab/USB auto-redirection. Lock diagnostic
window bounds after viewport readiness to prevent delayed preferred-size drift;
retain strict sampler aborts after geometry changes. Compare explicitLZ4 andOFF
in same runtime, distinguish bytes/commands/decodedIDs, trace observer costs.
On gain compare entire native client pixbuf with stable QEMU snapshots of a
static compressible pattern and high-entropy pattern. This qualifies only
server→client losslessness, not guest→capture or physical scanout/GPUFPS.

Build provenance ~/macos-vm/run/c439-spice-build-provenance.json; runtime image
pinned in experiments/pins-bochs-client-lossless.json. No hardware outcome yet.
All other roadmap work on hold. No new feature publication or60fps claim.
