# Candidate 381: physical viewport matching in the actual manager

Measurements, audio retry, ordinary restoration and shutdown/recovery completed. No lifecycle outcome is inferred from a
completed observer window.

## Identity and method

Candidate 381, version `1.0.381`, card `metal-209`, run
`96304b2a4befa1d44b4ce442c295a86d`. Built source
`6c02c4189de32391a7fb0b2a245f52e0094e9860`, build
`8921433ed961428880b20947e0fa0c71`, executable SHA-256
`00c4dbe2fca2d0f268339fd153d7f0987a5eb6cfa19266ad6153faf764ebfb94`.
This is the existing snapshot/changed-bounding-box presentation path, with the
existing presenter binary. The experiment changes guest mode and manager viewport,
not GPU code or the presenter's capture/copy logic.

Each case uses the existing 110-second mixed fixture, alternating 20-second
localized-token and smooth full-field phases (last phase 10 seconds), and a
100-second synchronous ROI event observer on the actual virt-manager connection.
The wrapper settles the requested logical widget allocation before attachment,
records GDK scale, and checks geometry/properties through completion. It refuses
an unachieved or changed allocation. This is sampled GTK geometry validation, not
a compositor scanout trace. `resize-guest=false`, scaling is enabled, monitor 0.
Snapshot counters are sampled separately using the identity-bound read-only reader.

The phase analyses use completed source DRAW IDs to associate manager observations
with phases, retaining two-second transition guards and counter-read endpoint
uncertainty. Guest and host clocks are not subtracted. ACK, QEMU publication,
client region invalidation, observed unique IDs and widget redraws remain different
quantities. Source DRAW completion is not physical presentation.

## Three-case results

| Case | Guest pixels | Logical viewport / GDK scale | Physical viewport ratio | Guarded full-field observed IDs/s | Post-start invalid tokens |
|---|---|---|---|---|---|
| scaled-4k | 3840×2160 | 1280×720 / 2 | 2/3 on both axes | 14.42 / 14.47 | 0 |
| matched-1440 | 2560×1440 | 1280×720 / 2 | 1 on both axes | 57.58 / 57.50 | 0 |
| matched-4k | 3840×2160 | 1920×1080 / 2 | 1 on both axes | 34.50 / 34.94 | 0 |

Scaled-4k: 3,824 valid samples, 3,822 unique IDs, eight startup invalids and zero
invalids after the first valid token. Guarded full-field QEMU publications were
38.66/40.02 per second while observed client IDs were 14.42/14.47. Localized
phases delivered 51.06–52.60 observed IDs/s. The maximum observed stale interval
was 115.4 ms; maximum heartbeat gap was 363.6 ms.

Matched-1440: 5,743 unique IDs, six startup invalids and zero post-start invalids.
All five usable guarded phases measured 57.50–57.58 observed IDs/s; full-field
client counts matched publication counts in these intervals. The maximum observed
stale interval was 39.9 ms; heartbeat gap was 356.8 ms.

Whole attachment-to-finish GTK draw instrumentation measured 3,824 completed draws
at 6.973 ms mean / 76.194 ms maximum in scaled-4k, and 5,749 completed draws at
0.157 ms mean / 1.149 ms maximum in matched-1440. There were no pending or reentrant
draw callbacks at these finishes. These are aggregate wall times including
widget descendants and scheduling, not per-phase costs, GPU times or scanout
latency. They must not be substituted for the cost of a full-field draw.

Matched-4k: 4,593 valid unique IDs, eight startup invalids and zero post-start
invalids. Guarded full-field observed IDs were 34.50/34.94 per second versus
34.56/35.00 QEMU publications. Localized intervals were 52.20–52.58 observed IDs/s.
The maximum stale interval was 56.0 ms and heartbeat gap 252.3 ms. All 4,601 widget
draws completed, averaging 0.472 ms (maximum 4.290 ms). Separately, the event
observer began 4,602 invalidation callbacks but completed 4,601: its final callback
triggered measurement termination before sampling/completion. No extra sample or
callback cost is imputed for that callback.

The first comparison changes both payload resolution and scaling. The third case
holds the 3840×2160 source dimensions fixed and changes the viewport to a physical
one-to-one match: observed full-field throughput improves from approximately
14.4 to 34.5–34.9 IDs/s, with substantially less whole-window GTK draw wall time.
This supports avoiding client-side scaling as a useful configuration improvement.
It does not establish identical upstream work: accepted snapshot ACK rates also
changed from 42.5–45.1/s to 35.2–35.5/s in guarded full-field intervals. The guest
workload shares resources with client rendering; do not claim a controlled
constant-production bandwidth benchmark or assign all remaining limits to one
stage. In the matched cases the client counts closely track QEMU publications.
The three bounded windows contain 14,160 valid token samples and no post-start
token failures; 22 startup failures remain in raw evidence. This does not erase
candidate 379's three post-start failures or qualify general full-frame atomicity.

## Source diagnostic and integrity limits

Only the first nonce (`9814b20171be92d0`) owns this run's actual source diagnostic.
It completed a 30-second window over source IDs 1–1793: 1,590 processed samples,
1,583 valid, seven unavailable (`error_8`), zero CRC/torn errors, 1,580 unique and
three duplicates. It skipped 213 IDs. Appended copies of this historical summary
in subsequent logs are not new source windows. The window excludes busy-dropped,
upstream uncaptured and later samples, and token checks do not validate all frame
pixels or source stability after checking. Manager startup invalids are retained
separately; they are not silently discarded from raw evidence.

No arbitrary-window auto-resize, all-manager support, universal 60 Hz, full-frame
atomicity, input, fresh-user installation or physical endpoint audibility is
qualified by these measurements.

## Audio, restoration and lifecycle

The first default-application audio attempt refused a route change; its independent
restoration receipt verifies original sink, volume, mute, defaults and owned-module
removal. The retained retry passes stereo frequency/channel analysis at 48 kHz:
left approximately 997.1 Hz, right 1498.6 Hz, with zero opposite-channel RMS in
single-channel phases. The independent post-retry restoration checks all pass.
This qualifies VM USB/QEMU/Pulse sample delivery, not physical endpoint audibility
or the separate Samsung HDMI baseline. The first refusal is not erased by retry.

After closing the snapshot owner, the retirement probe exited zero: legacy BAR0
mapping/unmapping succeeded for 64 MiB, ARM was NotReady (`e00002d8`), and staging
mapping was refused (`e00002c2`, zero address/length). The ordinary presenter then
started a fresh 3840×2160 capture, with awake assertions and the original agent
SHA-256 `b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82`.
Root visually reviewed the actual-manager desktop screenshot as readable.
The VM's exact identity remained alive after the owned viewer closed. Input was
not rerun in this experiment.

Private `terminal.json` records `guest-shutdown` and `process_exited=true`; outer
shutdown is `exited-after-guest-request`, verdict `CORE_PROBE_PASS` with no earliest
failure, and recovery is `recovered`, `authorizes_launch=true`.

Both capture hooks report `container-stopped-during-shutdown-wait`, deferred with
`shutdown_event_wait=true`, approximately0.394 seconds. Their witness exits137;
that is the helper, not the VM. `completed_original_zombie=false`. Critical capture
ended with recv-reset and console capture with clean EOF. The exact Docker event
history independently records container `die` exitCode0 and `destroy`, with no
`kill`/`stop` action in the retained interval. Combined with the actual controller
terminal, this supports natural container exit while preserving the hooks' distinct
observational outcome rather than rewriting it to `natural-container-exit`.

Capture quality is not perfect logs: retained events tolerate a terminal prefix
with zero corrupt lines, incomplete snapshot7 (404 valid chunks, no END), and
terminal18. The valid verdict and recovery do not erase that explicit terminal
capture limitation or close broader forced-stop/crash acceptance.

## Separate resize-transport inventory

The retained guest inspection finds an AppleVirtIOConsole IOKit personality matching
virtio device type 3, plus AppleVirtIOPCITransport. The requested standalone
AppleVirtIO executable path was absent. This is personality inventory, not evidence
that a QEMU virtio-serial port is attached, a usable BSD endpoint exists, or a
SPICE agent supports monitor configuration. No transport or automatic-resize
qualification is claimed; kernel-cache code inspection remains separate work.
