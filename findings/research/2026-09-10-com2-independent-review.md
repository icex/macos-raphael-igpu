# Independent review: COM2 guest producer

Date: 2026-09-10

Baseline: `d109910`

Scope: `src/CriticalUart.hpp`, the COM2 integration in
`src/RaphaelGPU.cpp`, and `tests/test_critical_uart.cpp`. The concurrent VMID1
diagnostic changes were treated as already reviewed and were not reassessed.
This was an offline source/test review: no build, staging, QEMU, VM, device,
sudo, reset, or GPU action was performed.

## Findings

### Medium: the producer can exceed its claimed absolute 180-second worker bound

`criticalDumpThread` records its start and then passes the full configured delay
to `IOSleep` (`src/RaphaelGPU.cpp:495-500`). `rgpudump` permits values through
300,000 ms (`src/RaphaelGPU.cpp:6467-6468`), so the thread can remain asleep for
300 seconds before it observes that the 180-second deadline expired. This emits
no late COM2 bytes, but it does not satisfy the implementation report's claimed
180-second worker bound.

There is also a smaller write-side overrun. After checking elapsed time, the code
initializes the UART and calls `writeReady` with a fresh fixed 160 ms deadline
(`src/RaphaelGPU.cpp:505-510`; `src/CriticalUart.hpp:108`). That deadline is not
clamped to the worker's remaining time. If the delay returns just before 180
seconds, readiness bytes may be emitted after the worker deadline. Snapshot
deadlines are correctly clamped later at `src/RaphaelGPU.cpp:522-524`.

Suggested correction: cap the initial sleep to the absolute deadline (or refuse a
configured delay at/above it), and pass the remaining worker budget into the
ready-marker emission just as snapshot emission does. Add a deterministic fake
clock/worker-policy test for both boundaries.

### Low: the maximum/retry tests do not establish the promised byte-exact parser boundary

The maximum-snapshot test checks only an upper bound, elapsed simulated wire time,
and the presence of the substring `RGPU_END2` (`tests/test_critical_uart.cpp:118-138`).
The partial-line retry test checks only that a delimiter substring exists
(`tests/test_critical_uart.cpp:99-116`). Neither test feeds the UART-produced
bytes to the unchanged parser, verifies zero corrupt lines, or compares the
maximum stream to an independently constructed exact byte sequence/hash. Thus
the stated test-plan requirements for byte-exact maximum lines and demonstrated
partial-line parser resynchronization are not covered by this unit test. The
separate tiny-guest qualification may cover the parser boundary, but it does not
make these guest unit assertions stronger.

Suggested correction: freeze the UART output from a small and maximum formatter
fixture, parse it with the unchanged parser, and explicitly assert that the
failed attempt has no terminal END while the following complete attempt is
accepted without corruption.

## Checks that passed review

- `src/CriticalReplay.hpp` is byte-identical to `d109910` (SHA-256
  `6f43686e00766d468326dfd018a97861e892686c8259d122e4a115d344e965ba`).
- The ready marker is exactly `RGPU_UART_READY ... port=2` and contains no
  `RGPU_CR2` substring (`src/CriticalUart.hpp:100-117`).
- Initialization uses COM2 base `0x2f8`, clears unknown DLAB state before IER,
  programs divisor 1 and 8-N-1, enables/clears FIFOs once, sets DTR/RTS, and
  rejects an absent `0xff` LSR (`src/CriticalUart.hpp:59-88`). Healthy attempts
  do not reset the FIFO (`src/RaphaelGPU.cpp:517-524`).
- Each byte has a 2 ms timeout and each snapshot has an absolute deadline. A
  timeout latches failure, so later callbacks including END become no-ops
  (`src/CriticalUart.hpp:24-41`, `91-98`, `120-121`). A retry reinitializes only
  after failure and prefixes CRLF, which is a valid line resynchronization shape
  (`src/RaphaelGPU.cpp:517-524`; `src/CriticalUart.hpp:91-98`).
- With `rgpucr2uart=2`, COM1 CR2 replay is suppressed and one separately started
  worker owns plugin COM2 writes (`src/RaphaelGPU.cpp:454-472`, `6485-6495`).
  With the flag absent or any value other than 2, the historical COM1 replay loop
  remains selected and no port I/O thread starts (`src/RaphaelGPU.cpp:6364-6368`,
  `6485-6495`). The additional boot-argument status record means snapshot content
  is not literally identical to the baseline, but the routing and formatter are.
- The implementation establishes one writer inside this plugin. It does not
  establish exclusive macOS ownership of COM2 against an Apple/ACPI serial
  driver; the implementation report correctly leaves foreign/conflicting bytes
  as a later capture failure condition rather than claiming that risk resolved.

## Local verification

The sanitizer-backed focused UART and unchanged replay C++ tests both exited 0
with `-Wall -Wextra -Werror`. `git diff --check` passed for the three reviewed
source/test paths.

Verdict: request changes for the absolute worker/readiness deadline. The UART
failure latch, FIFO-reset policy, flag-off routing, ready-marker namespace, and
formatter preservation are otherwise suitable for the next offline review gate.

## Coordinator review of corrections

The implementation agent addressed the deadline finding with a pure
`CriticalWorkerBudget`: initial sleep is capped, readiness receives the remaining
budget after initialization, and retries recompute remaining time after UART
reinitialization. The coordinator inspected those call sites and the deterministic
budget tests. These are bounded requested waits and emission checks, not a
real-time scheduling guarantee for a macOS kernel thread.

The UART tests now compare a small complete stream byte-for-byte with the
unchanged formatter, freeze the maximum stream FNV as `c4dc5b2650dfb248`, and
verify that a failed fragment has no END and is delimited from the exact retry
stream. The implementation agent reran UART/replay sanitizer tests and the
unchanged Python parser tests (17 passed). The original findings remain above
as review history; neither is an outstanding build blocker. Real dual-collector
qualification and host integration review remain separate acceptance gates.
