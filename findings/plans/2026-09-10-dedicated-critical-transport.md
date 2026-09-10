# Dedicated COM2 critical replay transport

Date: 2026-09-10

Status: implemented in the repository and independently reviewed. Ten real
CPU-only QEMU transport tests passed; final Python discovery ran 594 tests with
one explicit skip. Live harness deployment and a new candidate remain pending.
These checks establish tested capture behavior, not Metal execution or GPU reuse.

## Boundary and acceptance

CR2 currently shares COM1 with macOS `SYSLOG`. Candidate 183's GUI run proved that
Apple's AMD dump can interleave with CR2 at character granularity. The durable fix
is an opt-in second emulated 16550 at COM2, used only by CR2. The CR2 wire format,
`tools/critical-replay.py`, recovery lease formats, lifetime validation, and VFIO
recovery helpers remain byte-identical.

A candidate may select the new transport only with this manifest contract:

```json
{
  "critical_replay_schema": 2,
  "critical_replay_transport": {
    "kind": "isa-serial",
    "version": 1,
    "index": 1,
    "io_base": 760,
    "baud": 115200,
    "socket": "run/critical.sock",
    "capture": "critical.txt"
  }
}
```

The same object must appear in the experiment card and sealed manifest. Omission
preserves the current COM1 behavior for historical cards. Any partial, unknown or
mismatched object refuses staging or launch. `rgpucr2uart=2` must be present exactly
when this object is selected. A new run never falls back from COM2 to `SYSLOG`.

Acceptance requires a byte-clean complete CR2 snapshot in `critical.txt`, exact
COM1/COM2 topology and dual-collector readiness, unchanged parser acceptance, and
normal capture of COM1 in `serial.txt`. A missing, disconnected, timed-out, partial,
foreign, conflicting or lossy COM2 capture remains `capture_loss` and forbids
recovery/reuse. It is not repaired from COM1.

## Guest producer

Add `src/CriticalUart.hpp` containing only bounded x86 port-I/O and 16550 state.
COM2 is fixed at I/O base `0x2f8`, IRQ 3, UART index 1. When `rgpucr2uart=2` is
parsed, initialize it once from a normal worker context: disable UART interrupts
through its IER (do not disable CPU interrupts), set
DLAB, divisor 1 for 115200 baud, restore 8-N-1, enable/clear FIFOs, and set DTR/RTS.
Read back LCR and require a non-`0xff` LSR before publishing readiness. No IRQ
handler is installed; transmission is polling-only.

Each byte waits for LSR THRE (`0x20`) with a finite monotonic bound. The proposed
bound is 2 ms per byte with 10 microsecond polls. Normal 115200-baud timing should
complete far below the bound. The first timeout latches the current snapshot as
failed, makes all later lines of that attempt no-ops (including END), and reports
one ordinary COM1 status after leaving the emitter. The next scheduled snapshot may
reinitialize and try again. No byte is emitted from a driver hook, while holding an
X6000 lock, or from an interrupt context.

Implementation must also impose a total snapshot deadline: a per-byte timeout
alone can accumulate beyond the experiment's exposure budget. Qualify worst-case
wire size and elapsed transmission time in the tiny-guest test before selecting
that deadline. Refuse/omit END on an exhausted total deadline; do not extend the
host exposure limit to accommodate a slow diagnostic stream.

Split the current `diagDumpThread` responsibilities in `src/RaphaelGPU.cpp`:

- `diagDumpThread` retains the existing delayed human-readable COM1 diagnostics
  but no longer emits CR2.
- A new `criticalDumpThread` waits the same configured `rgpudump` delay, then emits
  up to 18 immutable cumulative snapshots at the existing 10-second interval.
  It is the sole COM2 writer. Snapshot IDs and `CriticalReplayV2::emitSnapshot`
  formatting remain unchanged.

The CR2 worker must start independently of the large COM1 diagnostic dump. This is
necessary because moving only the bytes to COM2 would still leave CR2 queued behind
hundreds of synchronous `SYSLOG` calls in the same thread. `criticalRecords` keeps
its existing immutable publication/read rules. If preflight sees an unpublished
slot, that attempt emits nothing and the next sequence is tried as today.

`CriticalReplay.hpp` should remain unchanged if the UART sink can latch failure
without changing the callback contract. The sink begins each attempt enabled;
after a timeout it silently discards the rest, including END. The caller logs the
latched failure only after `emitSnapshot` returns. This preserves the wire format
and prevents a terminal END from manifesting deliberately dropped chunks.

The driver should emit exactly `RGPU_UART_READY v=1 b=<32hex> port=2` once on
COM2 before snapshot 0, bound to the build ID and literal transport version.
The marker deliberately excludes the `RGPU_CR2` substring, which the unchanged
parser reserves for replay lines. Host readiness does not treat
that line as a valid snapshot; it only distinguishes a connected but unused COM2
from a configured producer. The unchanged parser ignores it.
Collector readiness and producer readiness are separate gates: supervision proves
that QEMU has both socket consumers before exposing success, while `experiment.py`
must observe exactly one matching producer-ready line before it admits the Metal
probe. Absence or conflict remains capture loss.

## QEMU and capture topology

In `/home/bogdan/macos-vm/macos-vm.sh`, make both UART identities explicit rather
than depending on option order:

```text
-chardev socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off
-device isa-serial,chardev=rgpu_console,index=0
-chardev socket,id=rgpu_critical,path=/run/vm/critical.sock,server=on,wait=off
-device isa-serial,chardev=rgpu_critical,index=1
```

COM2 is enabled only by a dedicated `CRITICAL_SERIAL=on` launcher setting supplied
by the supervisor for a manifested run. Do not accept it through arbitrary
`EXTRA`. Before Docker starts, unlink both known socket paths while holding the
existing launch reservation. No physical device, VFIO, sudo, or host serial port is
involved; both UARTs are QEMU devices.

Generalize `tools/sercat.py` with required environment values for socket, output,
ready path, CID, and channel (`console` or `critical`). Keep its current append,
unbuffered write, per-receive fsync, bounded connect, and EOF behavior. Default
values may preserve manual COM1 compatibility, but supervised launches must pass
every value explicitly. A ready file is written only after the correct socket is
connected and the output file is open; its content binds full CID plus channel.

`tools/vm-supervision.py` starts `rgpu-serial-<cid>.service` and
`rgpu-critical-<cid>.service` before declaring the run ready. It uses one absolute
readiness deadline for both, records both unit and ready-file identities in
`supervision.json`, and verifies both services are loaded, active/running, have a
positive PID, and publish the exact CID/channel token. Each service retains
`ExecStopPost=docker stop --time 0 <full-cid>`. Thus disconnect of either collector
stops the exact VM. The existing container deadline remains single and unchanged.
Cleanup stops both collector units only after exact-container stop is established;
failure cleanup does the same. Repeated exact-CID stops are harmless and never fall
back to a reusable container name.

`tools/redeploy.sh` rotates and truncates `critical.log` beside `serial.log` before
launch, without changing the GPU budget or safety gates. Its success message names
both live logs. The run finalizer copies them without newline normalization to
`serial.txt` and `critical.txt` and hashes both. Neither file is synthesized from
the other.

## Evidence routing and identity

`tools/experiment.py` validates the exact transport object, requires the critical
collector in live supervision, and adds `critical.txt` plus its SHA-256 to the
frozen evidence. The harness hash map continues to pin `macos-vm.sh`,
`vm-supervision.py`, and `sercat.py`; no helper hash is repurposed. Recovery receives
the bytes read from `critical.log` when and only when COM2 is manifested. Existing
schema-3 lease and two-live-lifetime-read requirements remain unchanged.

`tools/classify-run.py` parses CR2 exclusively from `critical.txt` for the new
transport. It separately scans `serial.txt` through a narrow console-only path for
panic and driver build identity. It must not feed COM1's damaged
or duplicate CR2 markers into the CR2 parser, and it must not duplicate ordinary
diagnostic events from both files. Conflicting driver build identity is fatal.
Review confirmed that the existing console protocol has no independent run-ID
or shutdown record to merge: run identity remains bound through the existing
CR2 lease/lifetime nonce, the probe result and `shutdown.json`. Those gates remain
unchanged. Historical manifests continue to read CR2 from `serial.txt`.

`tools/stage-candidate.py` validates the card's exact transport object and boot
argument, and preserves it in staging metadata. Candidate activation must verify
the staged launcher/supervisor/collector hashes after deployment, just as it does
for the present harness. This transport changes capture provenance, so the next
experiment card and its reviewed one-run policy must name `critical.txt` as the
authoritative CR2 input. It does not change the functional hypothesis by itself.

## Minimal implementation set

Production files:

1. `src/CriticalUart.hpp` — bounded COM2 initialization and byte sink.
2. `src/RaphaelGPU.cpp` — opt-in boot argument, independent CR2 worker, and COM2
   sink integration.
3. `/home/bogdan/macos-vm/macos-vm.sh` — explicit COM1/COM2 QEMU topology.
4. `tools/sercat.py` — parameterized, channel-bound collector.
5. `tools/vm-supervision.py` — dual service lifecycle/readiness/cleanup.
6. `tools/redeploy.sh` — rotate/create the second live log.
7. `tools/experiment.py` — manifest validation, live routing, freezing and recovery
   input selection.
8. `tools/classify-run.py` — manifest-selected critical input plus narrow console
   panic/shutdown merge.
9. `tools/stage-candidate.py` — exact card/staging transport contract.
10. The next experiment card — opt-in transport and `rgpucr2uart=2` requirement.

Tests:

1. `tests/test_critical_uart.cpp` for divisor/register order, absent UART, bounded
   THRE timeout, failure latch, no END after failure, retry on next snapshot, and
   byte-exact maximum CR2 lines.
2. `tests/test_vm_supervision.py` for both services, one shared deadline, exact
   ready tokens, either-channel timeout/disconnect, exact-CID stop, and cleanup.
3. A new `tests/test_sercat.py` for socket/output isolation, fsync-visible bytes,
   EOF, reconnect refusal and channel-bound readiness.
4. `tests/test_experiment.py`, `tests/test_classify_run.py`, and
   `tests/test_stage_candidate.py` for manifest symmetry, old-manifest compatibility,
   authoritative-input routing, COM1 corruption isolation, identity conflicts,
   recovery input selection and both frozen hashes.
5. Existing `tests/test_critical_replay.cpp`, `tests/test_critical_replay.py`, lease,
   lifetime, recovery, qualification and full Python/C++ sanitizer suites unchanged.

`RaphaelGPU.cpp` is concurrently being changed by the diagnostic implementation
agent. Land or inspect that work first, then apply the small integration hunks to
the resulting file; do not overwrite or transplant against the old line numbers.
`CriticalUart.hpp` and its unit test can be developed independently.

## Implementation order

1. Add failing pure C++ UART-sink tests, then implement `CriticalUart.hpp` without
   touching `RaphaelGPU.cpp` or the CR2 formatter.
2. Add failing collector and supervision tests, then parameterize `sercat.py`, add
   explicit launcher UARTs, and implement dual readiness/cleanup. Exercise only
   fake sockets and exact-CID command fixtures at this stage.
3. Add failing manifest, archive, classifier and recovery-routing tests, then add
   the opt-in contract to staging and `experiment.py`. Verify historical fixtures
   remain byte-for-byte routed through `serial.txt`.
4. After the diagnostic agent's `RaphaelGPU.cpp` work is stable, integrate the boot
   argument and independent worker against that exact source. Run syntax, UBSan and
   ASan fixtures before building a kext.
5. Run the tiny-guest TCG qualification below. Freeze its outputs and every changed
   source/harness hash for independent review. Do not proceed if QEMU qualification
   is skipped or either channel leaves residual ownership.
6. Build and stage the new candidate and card offline. Recheck boot image, manifest,
   QEMU argument order, both collectors, parser input selection, recovery helper
   hashes and the full regression suite. Hardware admission remains a later,
   separately reviewed coordinator decision.

## End-to-end transport qualification

Before any GPU cycle, run a GPUless TCG QEMU test with a tiny boot guest. The guest
initializes both 16550s, floods COM1 with strings containing deliberately malformed
CR2 markers while emitting a maximum-size, checksum-valid CR2 fixture on COM2.
Use the real two collector services and supervisor identity model. Assert:

- COM1 contains the noise and intentionally corrupted markers;
- COM2 is byte-identical to the generated fixture and the unchanged parser accepts
  it with zero corrupt lines;
- swapping sockets, CIDs, channel tokens or QEMU UART indices refuses readiness;
- failure to connect either socket before the common deadline stops the exact QEMU;
- closing either socket or killing QEMU at selected byte offsets preserves all
  fsynced bytes, produces only a complete earlier snapshot or an admissible existing
  open attempt, and never fabricates an END;
- normal exit stops both services and leaves no socket, service or pending-launch
  ownership that a later test can inherit.

Prefer a source-built 512-byte boot-sector fixture under `tests/fixtures/` and QEMU
TCG with a temporary raw drive. It needs no macOS disk, KVM, VFIO, host GPU, sudo or
network. If the environment lacks an assembler, check in the tiny binary together
with its source and SHA-256, and have the test verify the binary identity before
execution. Unit tests remain the required fallback in environments without QEMU;
the offline transport gate itself requires the end-to-end test to run, not skip.

After those tests pass, freeze the new tool, launcher, card and binary hashes and
perform an independent source/argument-order review. Only then may the coordinator
consider a separately admitted GPU run. A clean COM2 capture demonstrates reliable
transport; it does not demonstrate shader work, desktop presentation, queue
retirement, or future host safety.
