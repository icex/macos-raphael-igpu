# Candidate378: synchronous existing-channel event observer

Candidate376's mixed full-field HiDPI workload produced about39 QEMU surface
publications/s while its manager timer ran only about20 callbacks/s. Its sampled
14–18 distinct IDs/s therefore does not establish actual client delivery rate.
This candidate changes observation only. No guest binary, consent-bearing
presenter, driver, QEMU image, harness or native VM was changed or accessed.

## Smallest discriminator

`tools/console-manager-cadence.py --event-observer roi --roi-extension <file>`
attaches to the actual manager's existing SpiceDisplay and matching display
channel. It synchronously decodes the existing token ROI on each
`display-invalidate`. No extra SPICE connection, nested event dispatch, borrowed
pointer caching, background surface access or full screenshot is introduced.
The existing extension reacquires and copies the primary ROI under default
main-context ownership each time. It requires one monitor, surface0 at origin0,
widget monitor-id matching the monitor (or whole display -1), matching dimensions,
nongl little-endian32xRGB, and bounded token geometry. Wrong mappings fail; there
is no fallback to an unrelated primary or full snapshot.

`--event-observer count-only` records channel-wide invalidations without reading
pixels. It does **not** establish single-monitor pixel validity. Its finite
window starts at attachment; ROI mode retains first-valid-token start. Do not
compare raw whole-window totals between these modes. Default timer observation
is unchanged. Channel/display disappearance or replacement fails explicitly.

Each invalidation has a raw start timestamp/rectangle/index; completion records
carry callback duration. Widget draw callbacks are counted separately. A timer
only discovers/binds the existing channel, tracks scheduling gaps and enforces
the measurement deadline. The observer never consumes widget draw signals.
Callback cost includes begin/sample logging and excludes the final cost-record
write. A deadline-triggering callback can finish the measurement while still
inside its handler: the summary explicitly reports `final_callback_in_progress`
and counts only completed callbacks in cost aggregates. Its raw start is retained.
The last callback's unfinished cost is not invented. Final stale duration includes
any trailing silence since the last unique ID even if callbacks cease entirely.

## Why this callback is appropriate, and what it does not prove

Installed host package: `spice-gtk 0.42-5`; client is existing virt-manager5.1.0.
Official0.42 source retained under `run/c358-spice-source/spice-gtk-0.42`:

- `src/channel-display.c:1145` executes the canvas DRAW operation before
  `emit_invalidate` for a primary surface; `:1103` emits through the coroutine API.
- `src/gio-coroutine.c:190–237` emits on the main context, synchronously from the
  decoding coroutine's perspective; decoding resumes after handlers return.
- `src/spice-widget.c:2936–2990` handles invalidation by queuing a redraw. GTK can
  coalesce draws. Neither draw callbacks nor invalidations are scanout frames.
- `src/channel-display.c:411` defines MARK as expose state, not frame completion.

[Official release](https://www.spice-space.org/download/gtk/spice-gtk-0.42.tar.xz)
and [public display-channel API](https://www.spice-space.org/api/spice-gtk/SpiceDisplayChannel.html).
Current single-bbox QEMU emits a region application for each changed publication,
but generic SPICE can emit multiple rectangles. Count decoded unique IDs, not
invalidation events as FPS. Even zero token errors does not prove every pixel.
Synchronous ROI/Python/logging delays decoder resumption and can reduce delivery.
This observer removes timer-skipping ambiguity, not all observer effects.

## Software controls

`tools/spice-refresh-smoke.py --event-observer count-only|roi` exercises the exact
production `EventObserver` class on one offscreen SpiceDisplay. Serialized qtest
supplies640x480 token bands at60 requests/s through experimental staging/ACK.
TCG only; no macOS, KVM, GPU, network device or native manager connection.
The unchanged changed-bbox host QEMU is explicitly identified in the evidence.
Controls are sequential, not simultaneous; common interior means each producer's
own ACK interval excluding first/last0.5 seconds. Startup token0 is separate.

| Control | Interior span | Invalidations/s | Valid unique IDs | Invalid samples | Mean callback |
|---|---:|---:|---:|---:|---:|
|Count only|3.983s|59.505|not decoded|not decoded|0.008ms|
|ROI + count|3.983s|59.756|238|0|0.609ms|
|Deliberately split duplicate tokens|3.979s|43.986|23|152|0.681ms|

All final software QEMU processes exited0 through QMP quit; cleanup receipts
confirm stopped. Split mode deliberately holds an inconsistent copy for20ms,
so its lower producer/delivery rate is not comparable performance. Retained
raw starts/completions, samples, producer ACKs, counters and rectangles support
these numbers. This small software test does not reproduce native4K full-field
load or prove a throughput improvement.

Initial fixture failures are retained: variable shadowing raised inside its
GLib timer; Python's alarm exception was swallowed by GI and did not unwind the
main loop. The exact owned software QEMU and test process were terminated with
SIGTERM; this is **not** a clean QMP shutdown. The fixture now turns callback
exceptions into `Gtk.main_quit` and has a separate GLib deadline. An attempted
X11 control refused unavailable GTK backend and cleaned up; final controls use
available Wayland offscreen. Existing offscreen/GDK/theme warnings remain in raw
logs. No physical VM or cycle runner was touched.

Thirteen focused tests verify count-only versus synchronous ROI behavior, duplicate
IDs, exact-channel selection/ambiguity, malformed rectangles, reentrancy,
partial-attachment cleanup, idempotent disconnect, closing during decode,
trailing silence without another callback, and strict positive/negative verdicts.
Positive ROI requires multiple unique IDs and zero post-start invalid samples;
the deliberate split control requires detected corruption, even if no intact ID
is observed. Count-only has no pixel oracle.
Six existing timer/ROI tests remain green. An earlier full host suite passed1306 tests with8 skips in53.279s; it preceded
the final verdict/stale-tail fixes. Those final changes passed all13 focused
event tests and6 existing timer/ROI tests; root owns the merged379 full suite.
The software controls were rerun after the stricter verdict change. The later
stale-tail helper only changes manager summary finalization, not the exercised
EventObserver class; software receipt source hashes preserve that distinction.
`console-event-control-analysis-20261009.py` reproduces the final interior table.

## Next native observation

Root may add `--event-observer roi` to the actual-manager wrapper using the same
fixture/nonce, source IDs, exact VM identity, sampler extension and QEMU counters.
Retain timer baseline and event callback costs. Compare guarded mixed-phase
interiors; do not infer GPU FPS, physical scanout, exact latency or source CRC
qualification from this observer. Candidate376's source validator timed out
before fixtures, and this software work does not repair that missing evidence.
