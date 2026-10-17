# Candidate-205 KIQ cycle review

Date: 2026-09-13. This is a read-only adversarial review of the candidate-204
dequeue trace, the candidate-205 native-restore run, and the candidate-205
early stamp run. It does not authorize a launch or establish desktop Metal
execution.

## What the evidence establishes

The strongest new fact is a real native boundary crossing. In run
`7d4da601c37665b5237fc6e5c8aa50e2`, the authenticated `kiq-start` capture hit
the wrapper entry, the internal native boundary, and the wrapper return with
`result=0` (`native_reached=True`). The serial trace independently records
`native-restore=1`, exact image checks, and the native call being entered.
That proves the wrapper reached and returned from Apple's native start path.

It does not prove a working queue. Immediately afterward the readback was
`ACTIVE=1, RPTR=0, WPTR=0xa0, EOP=0`, and the first `waitForHwStamp(1)` and
`submitKIQFrame` both returned zero. The early stamp run then reproduced a
5004 ms wait ending in `KIQ_WAIT_FAILURE result=0`. No command buffer
completion or Metal probe result exists in either run. The `INVALID` verdicts
are also explained by missing ACTIVE recovery-pool records; that is a cleanup
authority failure, not evidence that the pool was safe to publish early.

The later candidate-205 memory capture adds a useful negative result: the
channel's timestamp pointer was the readable canonical CPU address
`0xffffffcd746bb040`, raw mode was `0xffffffff` (direct mode), and the bounded
timestamp value was `00000000` at both entry and return. The channel still
showed `requested_stamp=1, current_stamp=0`, and the wait returned zero after
`5003.158 ms`. The timestamp pointer was therefore not merely an inaccessible
CPU read, while its zero value still does not tell us whether the GPU executed
the queue.

The candidate's exact native-restore admission and the removal of the
mode-2 forced-ACTIVE fallback are proven safety/diagnostic changes. They
prevent guessed address repair and preserve the distinction between native
return, queue recovery, and host cleanup authority. They are not a proven fix
for GPU execution.

## Three falsifiable issues

1. **Native return may be only wrapper/API success.** `result=0` and an
   internal breakpoint show control flow, but not accepted HQD writes or
   fetch. This is falsified by a same-run write/read trace showing native
   dequeue restoration, RPTR/WPTR, EOP/MQD/PQ programming, ACTIVE transition,
   and a nonzero completed stamp.

2. **The unresolved dequeue may be stale queue state rather than the MQD
   address calculation.** Before candidate-205's native continuation,
   `ACTIVE=1, RPTR=0x86, WPTR=0xa0, DEQUEUE=1, POLL=0,
   DOORBELL=0x80000000`; the MQD/EOP image and ownership checks were exact.
   Those facts are compatible with a drain waiting on an old ring or VM
   translation, but do not identify which. This is falsified by tracing
   `DEQUEUE_STATUS`, `ACTIVE`, `HQD_ERROR`, VM-fault state, and native ring/MQD
   reads while preserving the exact selected queue and addresses.

3. **CPU-visible image correctness does not establish GPU-side accessibility.**
   The exact MQD/EOP image, readable channel/ring descriptors, and canonical
   timestamp pointer prove host mappings and selected addresses, but not that
   the MEC can fetch those addresses or that its old queue state can retire.
   This is falsified by native write/read tracing plus VM-fault and HQD status
   showing accepted MQD/PQ/EOP programming and a completed stamp.

## Decisive next experiment

Use one fresh, identity-bound diagnostic run with the authenticated native
boundary. First request the MEC's existing software-inactive state and read
back `MEC_CNTL`, `CP_STAT`, and selected HQD state. While held, invoke native
`startKIQ` and trace `DEQUEUE_REQUEST`, `DEQUEUE_STATUS`, `ACTIVE`,
`HQD_ERROR`, RPTR/WPTR, EOP, MQD/PQ bases, doorbell/poll control, selector,
and VM-fault status. Verify EOP/MQD/PQ readbacks before releasing the MEC
software-inactive state. The local HWLibs audit finds no MEC halt inside native
`0x14fb0..0x15a73`; this boundary distinguishes a native write/visibility
problem from a MEC unable to fetch. Do not issue a manual ACTIVE clear or
`DEQUEUE=2`. Only accepted native writes, explained ACTIVE behavior, and a
nonzero stamp establish queue recovery; all other outcomes remain
non-authorizing diagnostics.
