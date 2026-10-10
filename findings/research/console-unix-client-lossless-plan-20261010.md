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

## Candidate439 completed: lower traffic, no material delivery fix

Run0b1d233c6a38a5fa92d30e1296164cba, MODE2334, GPUbuild9020975c77324d2eb31486f8a44e9b46,
unchanged d1deade... source. Runtime SPICE SHAfde040d7d9195aca8503e592b8c4856ca5d3a190ada125d6583f2dbb30b6890d
verified against actual container file.1552hosttests8skip/25upstreamtests passed.

A window-bound lock triggered a pre-source geometry abort; exclude. B live API
used a non-existent GI alias and had no source fixture; no-valid-token is expected,
not corruption. C uses actual GI display_change_preferred_compression(7), which
forwards to the existing native channel API. Server preference capability6=true;
remote server LZ4 cap5=false is not the client's decoder capability and must not
be interpreted as missing client support. Static session property alone stores
a preference; explicit live channel invocation is retained with timestamp.

C actual scale2 1920×1080/3840×2160, source60, normal1440×900/GDK1, strict4s startup
settling with no locks and unchanged post-ready aborts.100sec observation4433unique,
48startup-invalid,0post-start/duplicates. Guarded full-field interiors23.47/23.50
client IDs/s, server44.33/43.11 commands/s; queue-busy91/109. Localized55.83–56.06.
Display-channel~195.10/195.22MB/s full-field,~0.05MB/s localized; substantial byte
reduction compared with prior raw rates but no material cadence fix. Distinguish
compression effect from actual negotiated wire enum (LZ4/LZ/raw fallback).

D rawX11 untraced,45sec userspace perf,60sec observer: full-field27.035, localized
55.68/56.02. E rawWayland untraced same60sec workload: full-field24.391, localized
54.44/55.14. Both actual Retina60/source60,0post-start invalid/duplicates. Final
short phase excluded. Sequential activity and profiler differences prohibit
regression/gain attribution; neither reaches sustained60. Wayland is not a fix.

Full-frame RGB: static color pattern matched stable before/after QEMU and native
SpiceDisplay pixbuf3840×2160 exactly. First late stage1 capture was desktop after
fixture closed: exclude from entropy qualification despite equal RGB. Dedicated
45sec entropy-only fixture then matched8,294,400 RGBpixels exactly, with4095/4096
unique center colors/stddev74 to confirm intended entropy visible. This is
server→client losslessness for two static frames, not guest→capture or moving
frames/alpha/physical scanout/GPUFPS. Initial PNG read raced in-progress save;
completed decode checked before accepting the comparison. Retain images/hashes.

Perf -B/-N still resolves libc names incorrectly under live symfs; exclude those
labels. Raw IPs and captured mapping offsets plus exact ELF files are retained.
Pixman hot offset0x854db resolves _mm_store_si128; libc0x17d8e7 etc remains unnamed
in debug info. Comm/DSO attribution valid, not sole-cause or saturation proof.

Artifacts c439-fourk-c-pipeline-analysis.json,c439-fourk-{d,e}-analysis.json,
c439-lz4-c-byte-analysis.json,c439-static-stage0-check.json,c439-entropy-check.json,
c439-*-pixel-hashes.json,c439-perf-elf-provenance.json,c439-perf-manual-offsets.json
and corresponding raw sources/logs/previews under~/macos-vm/run/.

Guest-requested exit/natural captures/private terminal verified; stopped-container
inspection reconciliation unavailable/mismatched. Recovery authorizes reuse. No
runner killed, no firmware/host binding changes, no feature publication. Next
bounded discriminator is completion-relative QEMU GUI pacing; no claimed fix.
