# Bounded primary-surface ROI observer control

Candidate346 adds an optional local research extension; it is not enabled in
candidate345 or any native run. No live VM, manager connection or visible window
was accessed. All source measurements use an isolated TCG Bochs fixture with one
offscreen SpiceDisplay and no GPU, KVM, guest OS or host network devices.

## Implementation boundary

`tools/console-token-roi.c` accepts a real PyGObject SpiceDisplay through the
PyGObject C API. It obtains that widget's existing session and unique matching
display channel; it never opens a connection or casts a Python integer/address.
It validates a single zero-origin monitor mapped to primary surface0, either the
matching monitor ID or whole-display ID-1. The initial implementation accepts
only nongl, little-endian Linux32-bit xRGB, positive bounded dimensions/stride,
and token scale1 or2. Unsupported geometry or mappings fail explicitly.

Both the Linux main thread and default GMainContext ownership are required.
This matters because a worker can acquire an idle context without becoming the
GTK thread. The helper reacquires the borrowed primary pointer each call and
copies two144×96 token rectangles, scaled when needed, into an owned compact RGB
byte string preserving the existing decoder coordinates. No pointer escapes,
no event loop is dispatched, and the GIL is never released while it reads.
The rest of the small320×160 canvas is zeroed. At2× scale it allocates614,400
bytes, versus a24,883,200-byte full4K RGB screenshot; only331,776 token RGB bytes
are populated. Current decoder logic is unchanged.

Source corroboration: official spice-gtk0.42 release,
`src/channel-display.c:540` returns borrowed format/stride/data;
`:1057` frees the data on canvas destruction; `src/gio-coroutine.c:207` delivers
signals through the main context. `src/spice-widget.c:3583` implements the
nongl full screenshot by allocating and converting every pixel.
[Release source](https://www.spice-space.org/download/gtk/spice-gtk-0.42.tar.xz)
and [public API](https://www.spice-space.org/api/spice-gtk/SpiceDisplayChannel.html).

## Paired observations

The same main-loop callback runs both the ordinary full get_pixbuf sampler and
ROI sampler, alternating their order. It checks sequence/nonce/CRC/error-category
agreement and byte-for-byte equality of both complete token rectangles. A small
unsampled RGB color sentinel inside each corner catches mistaken B/G/R conversion
that grayscale/magenta tokens alone would miss. Neither observer yields between
copies. All raw timings, errors, regions, producer ACKs and cleanup are retained.

Final helper,5-second controls:

| Surface | Paired samples | Disagreements | Full snapshot median | ROI snapshot median | Full/ROI with decode |
|---|---:|---:|---:|---:|---:|
|1920×1080,1×|620|0|0.878ms|0.020ms|1.358/0.500ms|
|3840×2160,2×|616|0|3.542ms|0.077ms|4.023/0.562ms|
|640×480 deliberate split|621|0|0.192ms|0.021ms|0.690/0.506ms|
|320×160 bounds control|621|0|0.041ms|0.022ms|0.563/0.512ms|

The bounds control additionally proves that asking for2× token coordinates on a
320×160 primary is rejected. Deliberate split generation gives546 invalid
samples; both observers retain exactly the same rejection semantics. Native-sized
and HiDPI controls retain5/16 invalid samples rather than suppressing them.
Every QEMU process exits0 through QMP quit. Earlier10-second exploratory controls
also show zero disagreements; their binary preceded the additional main-thread
guard and is identified separately in the evidence.

**Limits:** these are observer-cost and equivalence tests. HiDPI qtest hex writes
limit the producer to6.71/s; the1080p producer reaches60.02/s. They are not native
presenter throughput, GPU fps, complete-frame publication or scanout measurements.
Paired sampling deliberately includes both observers' load, plus pixel comparisons.
Alternating order reduces cache-order bias but does not reproduce manager workload.
The final timed controls did not overlap the parent's native345 measurements.

Invalidation remains a rectangular update notification; MARK is exposure state,
not per-frame completion. Lower observer cost does not reinterpret intermediate
regions as atomic frames. Both observers can faithfully agree on a partial token.

## Reproduce and validate

```
python3 tools/build-console-token-roi.py --output /new/local/extension
RGPU_ROI_EXTENSION=/new/local/extension python3 -B -m unittest discover -s tests -p test_console_token_roi.py
python3 tools/spice-refresh-smoke.py --qemu /path/qemu-patched --bios-dir /path/qemu-10.1.2/pc-bios --output /new/evidence --seconds 5 --rate 60 --roi-extension /new/local/extension --width 1920 --height 1080 --scale 1
```

The extension is built against the active Python and installed PyGObject/spice-gtk
headers with warnings-as-errors; it is never installed system-wide. Five real
extension tests cover wrong object/address surrogates, invalid scales, calls
outside main-loop dispatch, disconnected widgets and worker-thread context
ownership. They require `RGPU_ROI_EXTENSION`; ordinary portable host runs skip
these optional platform-dependent tests. No production harness/profile changes.

Validation completed: full host suite1,162 tests pass,8 skipped (including the
five optional observer tests); those five also pass when run with the built
extension. Binary/source/raw-record hashes are in the adjacent evidence JSON.
