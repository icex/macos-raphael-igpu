# Candidate 183 GUI capture analysis

Date: 2026-09-10

Run `4661e574bbd5695d00176d85bfa87325`, boot
`73ad3355-80a7-48f1-a8dd-e6f770b41de8`, build
`1d5f98d2e5b641eeab1869987f569e73`.

This investigation and its reconstruction are offline only. No VM, VFIO device,
BAR/MMIO, reset, recovery, or launch operation was performed. Raw progress is not
a verified Metal result: the capture has no accepted `RGPU_METAL_STAGE` or probe
result, and the frozen verdict remains `INCONCLUSIVE` / `capture_loss`.

## Finding

The failure is guest-side console multiplexing, not corruption introduced by the
host file writer. CR2 is emitted through `SYSLOG` onto the same console as Apple's
large AMD register/channel dump. The streams overlap at character granularity.
Twenty-four physical lines containing a CR2 marker are malformed mixtures of the
two producers. `sercat.py` receives the already mixed byte stream and fsyncs every
received chunk; fsync can affect throughput and persistence latency, but it cannot
explain bytes from two guest messages alternating within a line.

Only two snapshots reached an END:

| Snapshot | Records | Manifested chunks | Valid captured chunks | Result |
|---:|---:|---:|---:|---|
| 0 | 186 | 662 | 662 | Fully intact; CRC `dc5b31af`, FNV `d118231b8aa54652` |
| 1 | 265 | 915 | 508 | Terminal END intact; 407 chunks absent |

Snapshot 1 affects 92 records. The exact missing keys are `r003f p01`, all of
`r0040`, all of `r0041`, `r0043 p02-p03`, and all chunks of every record from
`r0044` through `r009a`. In detail, the all-missing records have these part counts:

```text
0040:1 0041:5 0044:4 0045:2 0046:4 0047:2 0048:4 0049:3
004a:10 004b:3 004c:6 004d:3 004e:5 004f:3 0050:3 0051:5
0052:2 0053:3 0054:2 0055:4 0056:2 0057:4 0058:2 0059:4 005a:6
005b-0062:7 each; 0063-0072:6 each; 0073-009a:4 each
```

Snapshot 0 is an exact donor for every missing key. Re-encoding those 407 donor
payloads with snapshot ID 1 and inserting them immediately before the original
snapshot-1 END makes the unchanged parser accept the original terminal totals and
digests: 265 records, 32,567 bytes, 915 chunks, CRC `479b28cb`, FNV
`a4dd20b0b45780c4`. Its first 186 reconstructed records equal snapshot 0 exactly.
This is an integrity-backed diagnostic reconstruction, not direct observation of
the erased physical lines.

Snapshot 0 contains the run-bound OWNED record at 43, ACTIVE POOL at 65, and VALID
lifetime at 66. It cannot be used as the terminal capture because snapshot 1 proves
that another 79 records existed. Accepting snapshot 0 directly would weaken the
later-snapshot rule and could hide a later ABORT or identity transition.

The 180-second run emitted 965,289 serial bytes (average 5.36 KiB/s). Snapshot 0's
region occupies 133,716 bytes; snapshot 1's region occupies 350,793 bytes because
it overlaps the AMD dump. The code sleeps 40 seconds before diagnostics, prints 256
ordinary diagnostic records, emits each entire cumulative CR2 prefix, then sleeps
10 seconds. Only snapshots 0 and 1 completed. There are no per-byte timestamps, so
the evidence cannot divide elapsed time precisely among guest `SYSLOG`, emulated
UART delivery, host receive, and fsync. It does establish that repeatedly emitting
roughly 700-1,000 text lines competes with the same high-volume console and consumes
a material fraction of the bounded run. The host fsync policy may add backpressure;
it is not the source of character interleaving.

The absence of probe markers does not prove that the probe never ran. It means the
shared serial capture did not retain admissible evidence of it. The run's raw mode-4
conversion and KIQ/doStop messages remain preliminary observations only.

## Proof-only reconstruction

`tools/gui183-capture-repair.py` is a separate, run-specific proof tool. It pins all
12 frozen run files, the run/build/boot identities, the five manifest recovery
helpers, both snapshot identities and END values, and the exact 407 missing keys.
It preserves every original serial byte and inserts only donor-derived, snapshot-1
bound chunks before the original END. It rejects artifact or helper drift, foreign
transport, later transport, valid prefix conflicts, unexpected missing keys, END
mutation, ABORT evidence, and lease/lifetime cardinality, nonce, or checksum errors.
It passes the derived transcript through the unchanged parser and writes only a
new exclusive proof/output namespace. It has no recovery or hardware action path.

The raw capture cannot authorize ordinary recovery. After independent source and
proof review, a later one-use coordinator could explicitly validate the exact proof,
derived-capture and tool hashes, then pass the derived text only in memory to the
unchanged `experiment.recover_v2`. That call must retain schema-3's current checks:
manifest/helper identity, exact run-bound OWNED and ACTIVE POOL records, first live
VALID lifetime read, a second identical live lifetime read immediately before the
first scratch write, queue retirement, host KIQ fence, PSP ring destruction, and
receipt refusal on incomplete retirement. No current coordinator path consumes
this new proof as ordinary authority; adding such intake is a separate reviewed,
run-specific change. The proof itself sets `authorizes_gpu_action=false`.

## Durable capture repair

The smallest durable change is a second emulated 16550/COM2 used exclusively for
CR2, retaining the current wire grammar and parser. Seal the extra QEMU device and
its dedicated socket/collector identities in the staged manifest. Emit from one
bounded guest worker, outside unknown driver hook locks, and serialize whole CR2
lines on that port. Capture to a separate append-only file with the same persistent
fsync policy. Ordinary Apple console output remains on COM1 and cannot interleave.
The supervisor must prove both collectors ready before launch and preserve current
deadline, exact-container teardown, sleep inhibition, and recovery-helper hashes.

Reading an immutable guest buffer through QEMU/GDB just before stop is weaker: it
depends on a responsive QEMU/control plane at the exact failure boundary and does
not reliably survive a host or QEMU crash. IORegistry has the same post-crash
availability problem. A dedicated emulated UART contains no host-GPU register
access and can retain bytes already emitted when the guest or QEMU exits.

Regression tests should first reproduce arbitrary character-level COM1
interleaving while asserting that the COM2 byte stream remains byte-identical.
Cross-language fixtures must cover maximum records and line sizes, partial final
writes, collector disconnect/backpressure, QEMU closure, duplicate snapshots,
foreign build/run identities, conflicting chunks/ENDs, stale/later snapshots,
ABORT after VALID, and output fsync/restart. An end-to-end GPUless QEMU test should
seal and verify the two chardev identities, kill QEMU at several byte offsets, and
show that the parser accepts only the last complete snapshot or the existing
explicit open-attempt rule. No parser relaxation is needed.
