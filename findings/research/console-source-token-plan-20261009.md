# Candidate367: bounded actual ScreenCaptureKit source-token validation

Set `RGPU_CONSOLE_TOKEN_NONCE` to exactly16 hexadecimal digits for an explicit
nonce-matched diagnostic. Unset means no source-region reads or diagnostic counts;
empty, wrong-length or nonhex values fail configuration before device lookup.
No duration strings are accepted: wait60s, then observe30s are fixed bounds.

Successful capture start arms the monotonic wait clock on the processing queue.
Before the first matching valid source token, processed unavailable/nonmatching
samples increment `waiting`; they do not start or poison the measurement window.
The first matching nonce/CRC/two-copy token selects1× or2× geometry, starts30s,
and is counted. Subsequent processing counts every sample entering presentSample:
valid, duplicate, invalid token, backward ID or unavailable (incomplete attachment,
format/geometry mismatch, mode transition or failed pixel lock). Geometry is pinned
for that window; a change is not silently a new experiment. Sources validated
inside the existing readonly CVPixelBuffer lock are checked **before** the normal
VRAM write. A failed source check never changes copy success or aborts presentation.

The shared C decoder implements existing Python token borders, five positions
per cell, >210 white/<50 black tolerances, nonce, big-endian ID, CRC and duplicate
agreement, reading locked BGRA without copying a full frame. Error categories:
1 bounds,2 border,3 ambiguous,4 torn cell,5 identity,6 CRC,7 duplicate disagreement,
8 unavailable,9 backwards. Valid repeated IDs count as duplicates, not invalid.
Source reads and checker time are separately accumulated. Existing total presenter
timing includes this diagnostic overhead; compare with diagnostics disabled before
making performance claims.

A processing-queue timer checks deadlines even with no arriving samples. It prints
one summary when60s expires with no valid token or30s expires after start; first
sample at/after deadline is excluded. Summary completion may be delayed by an
occupied serial queue; it never extends the counted window. Normal presenter
shutdown prints an interrupted marker and partial summary; fatal capture failure,
forced kill or process crash may leave no summary and is not a passing window.
No per-sample logs: configured/start/final summary only (plus interrupted if needed).
The presenter continues normally when diagnostic counting finishes.

Scope explicitly excludes busy-dropped callbacks, non-screen/invalid callback
buffers that never enter processing, frames upstream never captured, WindowServer
presentation completion, destination correctness, SPICE delivery and scanout.
Unavailable samples count invalid after start; they are not alleged corrupt pixels.
Existing source-copy experiment remains independent; do not enable both for cadence
comparison because that experiment adds memory traffic and full readback.

## Root-owned native plan

Compile the unchanged-identity presenter app with `console-source-token.h` beside
its source. The package includes/hash-verifies the new dependency and records it
in provenance. No TCC policy bypass: changed ad-hoc CDHash may require normal UI
renewal. First compile/sign and verify the exact bundle; no native work occurred367.

Run a60s known-nonce producer after capture arms, retain its DRAW log, source
summary, ordinary presenter timing/drop log and same actual-manager observer.
Require a completed30s source window; retain no-valid/partial results as such.
Source invalids localize a problem no later than the capture buffer; valid source
with invalid manager samples leaves VRAM/QEMU/SPICE as candidates. Neither result
alone identifies one transport stage or proves whole-frame atomicity.

Four focused tests compile C with warnings as errors and compare existing Python
fixtures at native/HiDPI, wrong nonce/CRC/duplicate/border/torn/ambiguous negatives,
malformed configuration, zero geometry and waiting/window/duplicate/backward/expiry
state transitions. Four source-package tests pass including actual embedded
manifest verification. macOS compilation, capture timing and runtime data remain
unqualified; no full suite or CPU-heavy/native run during366 measurements.
