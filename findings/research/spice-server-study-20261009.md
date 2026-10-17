# Candidate380: isolated SPICE server counters

Candidate379's native trace rejects pre-QXL creation throttling as the dominant
full-field gap: surface publications and QXL creation entries both~38–39/s,
while synchronous client invalidations~14.4–14.5/s. Localized updates~50/s match.
The next discriminator is server consumption, pending-draw removal and transport
progress, not a speculative GPU or framebuffer-copy change.

## Source and isolated builds

Actual native image package reports `spice 0.16.0-2` in
`~/macos-vm/run/c379-spice-package.txt`. This study uses upstream0.16.0, not a claim
of equivalence to all distribution-2 patches/build flags:

- [Official archive](https://www.spice-space.org/download/releases/spice-server/spice-0.16.0.tar.bz2)
- SHA256 `0a6ec9528f05371261bbb2d46ff35e7b5c45ff89bb975a99af95a5f20ff4717d`
- Local study: `~/macos-vm/run/c380-server-study/`
- Matched base/instrumented builds, release mode; GStreamer/SASL/smartcard/Opus
  disabled identically; LZ4 and mandatory JPEG/zlib/GLib/pixman/OpenSSL retained.
- Full resolved dependency versions, source/tool pins, artifact hashes and library
  paths: `build-manifest.json`. Meson1.9.1, Ninja1.11.1.4, pyparsing3.2.3, six1.17.0
  live only in the isolated build-tools venv.
- Host GLib pkg-config advertised missing `/usr/bin/glib-mkenums`. An isolated
  GNOME2.88.3 script (pinned hash) plus Meson native-file override supplies it.
  No host package, installed library, image or existing QEMU binary changed.

[Builder](../../tools/spice-server-study-build.py) accepts a fresh output directory
and explicit software QEMU binary. It rejects dependency version drift, applies
[diagnostic patch](../../tools/spice-server-study.patch) without fuzz, builds the
pair and verifies identical121 exported symbols and SONAME `libspice-server.so.1`.
This export check is not independent full ABI qualification; both builds share
all unmodified public source declarations. Retained `*-ldd.txt` verifies each
wrapper resolves its selected library.

## Source-supported counters

Source sites in upstream0.16.0:

- `red-worker.cpp:194–201`: QXL DRAW commands consumed and successfully parsed.
- `display-channel.cpp:482–499`: opaque equal-region replacement; older pending
  drawable is removed from client pipes. Count actual linked per-client pipe
  entries before removal, not merely removal calls on already-dequeued items.
  The shared helper also counts other removal paths; equal-removal subset is
  separate. These are per-client entries, not unique source frames.
- `dcc-send.cpp:960`: DRAW_COPY marshalling entry/completion and elapsed microseconds.
- `red-channel-client.cpp:938`: successful write bytes, completed outgoing-buffer
  count/bytes and EAGAIN occurrences on display channels only. Completion means
  bytes accepted by the transport write path, **not client display or scanout**.
  These cover all display messages, not exclusively DRAW_COPY. Buffers that cross
  a measurement boundary can contribute different write/completion byte totals.
- `pipe_item_get`: blocked-send and ACK-wait *poll observations*. These are counts,
  not durations or transitions; one condition can be observed repeatedly.

The patch does not change drawing, coalescing, compression or queue policy.
The existing `AF_UNIX` compression bypass remains in `dcc-send.cpp:439`.
Counters aggregate all display clients in one QEMU process; use one controlled
client and fresh process per case. Global pipe counts are not per-monitor evidence.

## Bounded collection and wrapper

Set `RGPU_SPICE_STUDY_SECONDS=15` (1..120) and optionally
`RGPU_SPICE_STUDY_DELAY=3` (0..30), then select `instrumented-qemu`; use `base-qemu`
for the matched control. Both executable wrappers are in the study directory.
The wrapper validates TCG/no-defaults/no-display and exact software Bochs fixture
arguments, rejects drives/KVM/VFIO/network devices, verifies QEMU/library hashes,
refuses injected loader hooks and sets only the selected library search path.
It does not launch a fixture by itself. Existing fixture owns process deadline
and cleanup. [Wrapper implementation](../../tools/spice-study-qemu.py).

The window starts relative to the first counter call, plus configured delay.
Counter increments are accepted only within that monotonic window. A GLib timer
emits one `RGPU_SPICE_STUDY` JSON line on stderr; normal unload/exit emits an
incomplete result if the window has not finished. SIGKILL can leave no report.
No per-frame logs, new worker thread or unbounded observation window. Timer
scheduling can delay publication; use embedded start/end timestamps for duration,
not when the line was read. Counts at boundaries are concurrent samples, not a
cross-thread atomic transaction. In particular, a producer can pass the time/report
check, pause, then increment after the reporting thread has loaded that counter.
Such an in-flight increment may be absent from the report. Conversely, some
concurrent increments can land before their individual counters are loaded. Do not
assert exact cross-counter conservation or infer one missing update from small
boundary differences; use stable large gaps and repeated matched windows. Invalid configuration emits one refusal line and
leaves counters disabled. Unset configuration disables counters.

The instrumented binary still adds branch, clock and linked-list lookup overhead;
matched controls must quantify its effect. It is not claimed observationally free.

## Validation and experiment plan

Both shared libraries compile.121 exported symbols match; dependency resolution
selects the intended library. Script compilation, software-wrapper rejection cases
(KVM, drive, VFIO, TCP listener, host-memory object) and independent patch application
with byte comparison to the built source pass; see `wrapper-checks.json` and logs.
No host-wide installation, hardware test or guest launch was performed by this task.

Use root-owned compact-band software fixture at native/4K with localized and actual
full-field damage. Legacy full-width hex qtest writes limit production to~6.5/s and
cannot reproduce native38/s behavior. Record achieved ACK/publication cadence,
background verification, valid source tokens, client counts and QEMU cleanup.
Do not compare mismatched producer rates or call a software-case result native
qualification. Root owns matched performance runs and their outcome report.

Discriminator: DRAW consumption near QXL creation, removals accounting for missing
client commands and lower marshal/send counts identify server-side pending update
replacement. Marshal/send counts near creation but fewer client invalidations
move the discrepancy later. EAGAIN/ACK poll counts and successful byte totals
indicate backpressure observations, not its ultimate CPU/client cause. Never disable
coalescing or enlarge queues simply to make counts match.

## Completed software experiment, 2026-10-09

Five formal 20-second cases used the same fixture, compact token writes, verified
full-field background changes and one client. Root retained the fixture before
subsequent edits as `c380-server-study/fixture-used.py`, SHA256
`86ea80b4c87c3da05ab1aaf4e13ca3b558b397864855f30c198b228b65d71f8e`.
Earlier producer-development and preliminary cases used changing fixtures and are
not formal matched controls. All five formal cases passed token/background checks,
reported zero post-start invalid samples and exited QEMU with status 0.

[Evidence JSON](spice-server-study-evidence-20261009.json) contains every raw-file
hash, selected binary identity, geometry, whole-run timing and aligned server
windows. [Offline analysis](spice-server-study-analysis-20261009.py) reads raw
artifacts and writes an exclusive derived output. Its seven negative checks reject
missing/duplicate/incomplete reports, missing or invalid counters, an unexpected
wrapper and missing cleanup. Retained validation: `analysis-checks.json`.

| Formal case directory under `~/macos-vm/run/` | Source pixels | Widget logical / GDK scale | Whole-run producer ACK/s | Client samples/s | Mean GTK draw |
| --- | --- | --- | ---: | ---: | ---: |
| `c380-base-fullfield-4k` | 3840×2160 | Offscreen 1280×720 / 1 | 55.51 | 26.80 | 25.60 ms |
| `c380-instrumented-fullfield-4k` | 3840×2160 | Offscreen 1280×720 / 1 | 55.33 | 26.85 | 25.68 ms |
| `c380-instrumented-window-fullfield-4k` | 3840×2160 | Visible 1280×720 / 2 | 57.07 | 15.40 | 48.75 ms |
| `c380-instrumented-window-matched-pixels` | 2560×1440 | Visible 1280×720 / 2 | 60.00 | 57.80 | 0.52 ms |
| `c380-instrumented-window-4k-one-to-one` | 3840×2160 | Visible 1920×1080 / 2 | 43.12 | 42.55 | 1.70 ms |

GTK averages divide whole-run accumulated draw time by completed draws. They do
not describe the 12-second server window. Requested logical widget dimensions
alone do not establish comparable rendering geometry: offscreen GDK scale 1 and
visible scale 2 differ. Multiplying allocation by GDK scale makes the last two
visible cases match their respective source dimensions; neither needed a filter
or server policy patch. Changing source size in the fourth case also changes
payload. The fifth case retains the 4K source, but changes widget allocation and
achieved producer cadence, so it is a stronger payload control, not a perfectly
isolated CPU benchmark.

For each instrumented case, half-open server timestamps were aligned directly to
producer ACKs and client invalidations on the same host-monotonic clock. Each
complete server window was 12 seconds and fully covered by producer records:

| Case suffix | Producer ACK | DRAW consumed | Actual pending removal | COPY marshalled | Valid client samples |
| --- | ---: | ---: | ---: | ---: | ---: |
| `fullfield-4k` (offscreen) | 665 | 522 | 200 | 323 | 323 |
| `window-fullfield-4k` | 682 | 522 | 338 | 184 | 184 |
| `window-matched-pixels` | 720 | 693 | 0 | 693 | 693 |
| `window-4k-one-to-one` | 519 | 518 | 5 | 513 | 513 |

These are observed stage counts, not exact conservation equations. The offscreen
residual `DRAW - removal - COPY = -1` illustrates boundary/lifecycle uncertainty.
No source frame IDs accompany server counters. Producer ACKs also include frames
replaced before publication, so ACK minus DRAW is not a server-drop count.

The scaled-window case demonstrates actual pending-pipe replacement downstream
of QXL consumption. In the same 4K source case with one-to-one device pixels,
GTK mean draw cost fell from 48.75 to 1.70 ms, observed pending removals fell from
338 to 5, and client rate rose from 15.40 to 42.55/s. This strongly supports client
rendering/scale cost as a software-fixture bottleneck that propagates backpressure
and replacement upstream. It does not identify every cost inside GTK, prove the
native manager uses exactly the same path, or establish native 4K 60 Hz.

The offscreen base/instrumented client rates differ by only 0.05/s in this pair;
this bounds the observed effect for that case, not overhead under every workload.
In its 12-second instrumented window, successful writes were 10,716,104,425 bytes,
with 6,981 EAGAIN/blocked poll observations and no ACK-wait polls. That demonstrates
transport backpressure observations; it is not proof of a physical network limit
or an ACK-window cause. Approximate rates and counter differences cannot establish
that all bytes reached a client or were visibly scanned out.

Identity limitations: analysis verifies selected wrapper, current pinned QEMU and
library hashes, and complete report presence. Build-time `ldd` verifies library
resolution. No per-run retained process-maps attestation exists, and this software
pair is upstream SPICE 0.16.0, not proven binary equivalent to image package
0.16.0-2. The builder was checked through equivalent isolated manual builds and
its finalization path; the complete fresh-output CLI was not rerun end to end.

The next clean discriminator is native manager geometry and draw timing with
source format and payload retained. Do not disable coalescing, increase queues or
change GPU copy semantics based on these counters. This result qualifies the
software diagnostic and motivates a client-side measurement; it does not qualify
the hardware desktop, input, audio, capture lifetime or recovery.
