# COM2 guest producer implementation

Date: 2026-09-10

Scope: source integration and pure C++ tests only. No kext build, VM, QEMU, GPU,
host device, staging, or recovery action was performed.

## Result

`src/CriticalUart.hpp` implements the opt-in polling producer for the emulated
COM2 UART at I/O base `0x2f8` (UART index 1, logical port 2). Initialization first
forces LCR to 8-N-1 to clear an unknown DLAB state, disables the UART IER without
changing CPU interrupt state, programs divisor 1, enables and clears FIFOs, and
sets DTR/RTS. It refuses an `0xff` LSR and verifies LCR plus LSR before use.

Each byte polls THRE every 10 microseconds for at most 2 milliseconds. Each
snapshot also has an absolute 110-second deadline. A failure latches the attempt;
later callback invocations, including END, emit nothing. Every attempt starts with
a bounded CRLF delimiter so a partial failed line cannot absorb the next attempt's
first CR2 header. Reinitialization clears the latch for the next scheduled attempt.

`src/RaphaelGPU.cpp` parses only `rgpucr2uart=2`. With it disabled, the historical
COM1 `SYSLOG` replay loop remains in `diagDumpThread`. With it enabled, that loop is
suppressed and a separate `criticalDumpThread` is the sole plugin COM2 writer. The
worker starts independently, publishes exactly
`RGPU_UART_READY v=1 b=<32 lowercase hex> port=2`, and formats snapshots with the
unchanged `CriticalReplayV2::emitSnapshot`. It logs UART failures through ordinary
COM1 only after the formatter returns. A healthy UART is not reinitialized between
attempts, avoiding an FCR reset while prior bytes may remain queued; only a failed
attempt is reinitialized. `CriticalWorkerBudget` caps the initial `rgpudump` sleep,
readiness write, each snapshot, and inter-attempt wait against one 180-second
absolute budget. A configured delay of 300 seconds is therefore capped at 180
seconds and produces no late readiness bytes.

This establishes one deterministic writer within this plugin. The offline test
does not prove that macOS has no Apple16X50 or ACPI driver probing COM2; foreign or
conflicting bytes must therefore remain a host-side capture failure. No ACPI or
platform serial ownership change is included.

## Bounds

The maximum formatter input is 512 records of 511 printable bytes. Each record
uses 13 chunks. Using the formatter's declared maximum physical lengths, including
CRLF and the attempt delimiter, the conservative bound is:

```text
2 + (512 * 13 * (172 + 2)) + (206 + 2) = 1,158,354 bytes
1,158,354 * 10 / 115,200 = 100.552 seconds
```

The 110-second snapshot deadline leaves about 9.45 seconds above this conservative
wire-time bound. The fake uses 87 microseconds per byte (the ceiling of one
10-bit 115200-baud frame), yielding a still-conservative maximum below 110 seconds.
The 2-millisecond byte timeout remains independently effective under THRE
backpressure; the total deadline prevents it accumulating once per byte.

The coordinating offline QEMU qualifier measured its maximum snapshot at about
1.142 MB in 1.169 seconds under the emulated UART, versus about 99.174 seconds at
nominal 115200-baud wire throughput. That qualifies the 110-second cap for the
emulated transport while leaving the calculation above as the conservative guest
deadline basis.

The maximum pure formatter/UART fixture freezes the complete 512-record stream at
FNV-1a64 `c4dc5b2650dfb248`, in addition to checking its byte count and simulated
wire time. The small fixture compares every UART byte with the CR2 formatter's
reference lines. Its failed-attempt/retry case proves the failed fragment has no
END and the complete retry begins after a CRLF boundary with byte-exact formatter
output. The unchanged Python parser remains covered by its existing suite and the
offline tiny-guest qualification; the C++ unit does not embed or modify it.

## Test evidence

TDD red checks were observed for the missing header, the corrected readiness token,
DLAB-safe register ordering, retry delimiter behavior, missing absolute-budget
helper, and frozen maximum-stream hash before implementation.
The focused verification command is:

```sh
g++ -std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
  tests/test_critical_uart.cpp -o /tmp/critical-uart-test && /tmp/critical-uart-test
g++ -std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
  tests/test_critical_replay.cpp -o /tmp/critical-replay-test && /tmp/critical-replay-test
python3 tests/test_critical_replay.py
git diff --check -- src/CriticalUart.hpp src/RaphaelGPU.cpp \
  tests/test_critical_uart.cpp \
  findings/research/2026-09-10-com2-guest-implementation.md
```

Both sanitizer-backed C++ tests exited 0. The unchanged Python parser suite passed
all 17 tests, and `git diff --check` exited 0. A driver syntax/build check is
intentionally deferred to the coordinating audit, as required by the task boundary.
