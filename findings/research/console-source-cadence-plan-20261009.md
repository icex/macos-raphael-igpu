# Candidate365: bounded source-cadence discriminator

The352/353 ON comparison copied4K rows in about1.48ms, but its AppKit producer
supplied only37–38 draw IDs/s. Delivered32–35 updates/s therefore cannot establish
a60Hz transport ceiling. Original fixture and transport remain untouched.

`tests/console_source_cadence.m NONCE SECONDS baseline|prerendered` supplies two
modes. Baseline retains original NSTimer1/60, full background and individual cell
drawing. Prerendered precomputes compact38×12 RGBA bands for successive IDs before
timing; nearest-neighbor8× draws identical token geometry. CVDisplayLink tied to
the actual NSScreen requests invalidation, with at most one pending main-queue
request. If display-link creation fails, the fixture fails; no timer fallback.
It reports nominal refresh, request/coalescing counters and actual drawRect IDs.

Sequence advances only inside drawRect; DRAW is logged after drawing calls
return. It is **not** a scheduled-timer count, completed WindowServer composition,
GPU fence, ScreenCaptureKit presentation or scanout. CVDisplayLink requests are
separately labeled and cannot establish completed frames. Pool exhaustion fails
rather than repeats IDs. Up to120s and120 draws/s plus16 bands are allocated
(~26MiB pixel storage maximum, plus CoreGraphics objects). No mode changes,
transport changes or second viewer. A wall alarm bounds fixture/setup lifetime.

## Root-owned macOS build and qualification

Compile with Command Line Tools (source/header in same directory):

```
xcrun clang -O2 -fobjc-arc -fblocks console_source_cadence.m \
  -framework AppKit -framework CoreVideo -o console-source-cadence
```

Record source/header/executable hashes and compiler. Launch under the logged-in
GUI user, retaining existing awake assertions, same image/fullrefreshON, signed
presenter, guest geometry and actual manager observer. First verify rendered
band orientation and native/HiDPI scale with existing decoder; host tests cannot
qualify the AppKit coordinate transform. If display-link cannot bind the virtual
display or decoding fails, stop and retain failure rather than compare rates.

Use fresh nonces and60s fixtures; sample the same30s middle interval with the
existing in-process ROI observer. Run baseline/prerendered at1080HiDPI, then
reverse order if needed; avoid concurrent host builds. Retain DRAW timestamps,
manager raw tokens, presenter timing and drop counters. Compare producer actual
DRAW IDs with copied and manager unique IDs for the same interval. Existing
presenter counts copied frames and rejected busy callbacks, not every complete
SCK arrival; do not infer unseen stages from those counters. A new counter is
not required for this first discriminator.

If source reaches near60 while manager stays near35, source alone does not
explain the remaining bottleneck. If both rise, the old fixture materially
limited prior cadence evidence. Neither outcome proves atomic whole frames.
Bochs Y_OFFSET provides no completion fence;64MiB fits two4K buffers but no safe
reuse acknowledgement. SPICE rectangular updates remain a separate boundary.

## Offline validation and limits

Two Linux tests compile the shared C band generator with warnings as errors,
expand nearest-neighbor native/HiDPI bands and decode them using the existing
nonce/CRC/duplicate parser; wrong nonce and corrupted duplicate refuse. Original
fixture is unchanged. No macOS compilation, GUI, guest, hardware or timing run
has occurred for365. Actual producer/display-link timing and its overhead remain
unqualified until the root-owned test.
