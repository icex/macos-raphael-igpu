# Candidate375: bounded mixed-damage stability fixture

Source-only change based on candidate374
`ee7c84e8715aaad48bc5a10ff0cd7970f6f5b6c4`. No native compile, guest execution,
image/helper staging, driver optimization or hardware work by this coordinator.

## Explicit opt-in

The existing `tests/console_source_cadence.m` accepts one additional mode:

```text
console-source-cadence NONCE16HEX SECONDS mixed
```

Nonce validation and the finite1..120-second limit remain unchanged. `baseline`
and `prerendered` retain their existing drawing/scheduling behavior and output.
Mixed uses the same CVDisplayLink pacing, pre-rendered nonce/sequence/CRC token
band and two copies. It does not change display modes or capture the screen.
The existing alarm remains an independent seconds+10 process bound.

Every20 seconds, the workload alternates:

- **localized:** constant0.12 white background; only the original token band
  changes logically, despite the view's normal redraw.
- **full-field:** a smoothly rotating dark gradient, with endpoint amplitude
  `.035*sin(pi*t/20)^2` around0.12. Its white values stay0.085..0.155 and amplitude
  and its first derivative return to zero at phase boundaries. No rapid
  high-contrast full-screen flashing is introduced. Existing token colors remain
  unchanged.

A uniform8-bit low-contrast ramp would quantize to only a few distinct whole-screen
values. A spatial gradient distributes threshold changes across the screen and
exercises large bounding rectangles without brightness flashes. The fixture is
still a workload request: actual full-field pixel damage, composition and60Hz
output must be observed, not inferred from the gradient or display-link timer.
NSGradient allocation/drawing adds source workload intentionally; any cadence
change cannot be attributed solely to transport.

## Logs and phase attribution

`MIXED_BEGIN` records monotonic guest epoch, duration and range. `MIXED_PLAN`
records all nominal phase windows up front, including a truncated final phase.
`MIXED_PHASE` records each actually drawn phase's scheduled boundaries and its
first completed drawing-call ID/time. A stalled/skipped phase remains visible in
the planned versus actual records. Existing `DRAW sequence time` lines are
unchanged in shape and IDs never reset across phases. `MIXED_END`, `TOKEN_DONE`
and `SOURCE_DONE` report bounded completion.

These are drawing-call completion records, not completed composition, capture,
manager delivery or scanout. Attribute valid manager samples to phase using
sequence IDs and actual phase-transition records; do not subtract unrelated
host and guest clocks to claim absolute latency. Invalid token samples have no
trusted sequence and should be reported with their observer-time bracket.

## Proposed next native protocol, parent owned

Two separate110-second fixture runs (e.g. HiDPI and native1080p), each with a
fresh nonce and100-second actual-manager observation nominally starting10 seconds
into the fixture. The intended[10,110) interval contains50 seconds localized and
50 seconds full-field changes, including the final truncated10-second phase.
Use actual logs to account for startup/jitter rather than assuming perfect timing.
Together this is220 seconds of workload and200 seconds of sampled observation.

Retain source fixture logs, raw manager samples/invalid reasons, per-phase valid
unique IDs and observed stale intervals, presenter timing/drop counters, final
normal desktop screenshot and unchanged ownership/cleanup receipts. Compare
localized and full-field sections within each run; do not call a reduced full-field
rate a driver regression without separating source production and transport.
No threshold or pass conclusion is invented in this source preparation.

The current presenter source-token diagnostic still covers only its existing
bounded30-second window. This fixture does not silently extend that diagnostic;
source CRC integrity throughout110 seconds would need separate evidence. Manager
nonce/CRC checks continue for the complete observer window.

Native compilation must transfer all three source files together:
`console_source_cadence.m`, `console_cadence_band.h`, and new
`console_cadence_phase.h`. Compile with the existing optimized AppKit/CoreVideo
command and record resulting source/binary identities. Native AppKit gradient
orientation/appearance and compilation remain unqualified until that run.

## Focused offline validation

`test_console_cadence_phase.py` compiles the exact phase helper and checks accepted
mode names,20-second boundaries, truncated duration, bounded smooth color values,
and rejection of nonfinite/out-of-range/expired inputs. Four tests pass in0.067s.
The existing two compiled token-band/decoder tests also pass in0.042s, preserving
nonce/CRC/two-copy geometry. Logs:
`run/c375-mixed-phase-tests.log`, `run/c375-token-band-tests.log`.
No heavy host suite or QEMU build was run during candidate374 measurements.
