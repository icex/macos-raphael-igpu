# Candidate 190 capture audit — 2026-09-10

Candidate 190 is invalid because its critical replay never produced a complete
snapshot after snapshot 3. This is missing evidence, not a parser defect. The
frozen output is `/home/bogdan/macos-vm/run/metal-024-190`.

## Exact evidence

- `capture-sha256.json` binds `critical.txt` as
  `17c071a1463a578913cfed84278d9b4ad069ae8b9966e46914bd6af6289be13a`.
- `critical.txt` has complete `RGPU_END2` records only for snapshots 0–3, at
  lines 60, 110, 160, and 210. Snapshot 3 certifies only its 22-record prefix.
- The guest serial reports `critical COM2 snapshot N transmission failed` for
  snapshots 4–13: line 4429 (4), lines 4658 and 4660 (5–6), lines 4686–4689
  (7–9), line 4696 (10), lines 4701–4702 (11–12), and line 4720 (13).
- The final physical line, `critical.txt:2324`, starts snapshot 13 record 2 part
  2 with `n=15 c=3ed9b001 d` but contains no payload. The line and record are
  incomplete.
- Strict parsing reports `CR2 has an incomplete transport line`. The recovery
  mode's open-attempt parsing reports `CR2 incomplete attempt exceeds the
  terminal prefix`: incomplete snapshots after snapshot 3 contain valid records
  beyond the last certified 22-record prefix. Discarding them could hide later
  abort or cleanup evidence.
- `recovery.json:2-3` therefore records `status: failed` and the exact
  `CriticalReplayError`. `verdict.json:2-12` correctly records `INVALID`,
  `capture_loss`, and `critical capture remained incomplete at exposure
  deadline`.

The ordinary serial log contains later diagnostic facts, including repaired
VMID2 roots and growing workload counters. They are not a complete authenticated
CR2 snapshot and cannot certify the final state or cleanup. The failed recovery
produced no receipt that authorizes another launch. Candidate 188's earlier
receipt authorizes only a separately reviewed finite launch; it does not turn
candidate 190's failed recovery into reusable authority.

## Mechanism hypothesis

`CriticalUart::put` has a 2,000 microsecond per-byte timeout and an independent
110-second whole-snapshot bound. If THRE is busy, the worker polls every 10
microseconds and permanently fails the current attempt when the per-byte timer
expires. Host scheduling delay is one possible explanation for the repeated
failures, but the capture does not prove it. A delay longer than 2 ms alone is
insufficient: the LSR must still report THRE busy when the timeout condition is
checked. If THRE is ready on the next read, the byte proceeds unless the
independent snapshot deadline has expired.

## Discriminating offline test

Add a fake-I/O `CriticalUart` fixture that controls LSR and the monotonic clock:

1. Keep THRE busy through 1,990 microseconds, then make it ready; the byte must
   succeed.
2. Keep THRE busy through the timeout check after 2,010 microseconds; the byte
   must fail.
3. Inject a one-time scheduling jump beyond 2 ms but make THRE ready on the next
   LSR read; this must succeed and prevents attributing failure to elapsed time
   alone.
4. Inject the same jump while THRE remains busy at the check; this must fail
   under the current implementation.
5. For any proposed preemption-tolerant rule, retain and test the independent
   110-second snapshot ceiling, exact wire checksums, terminal markers, and
   parser refusal of conflicting or incomplete later evidence.

The fixture was implemented without changing production behavior. It confirms
that a clock jump beyond 2 ms fails only when THRE was observed busy at the
timeout check; a 3 ms jump followed by an immediately ready LSR still writes the
byte. It also confirms that the independent snapshot deadline refuses an
immediately ready byte once the total budget has expired. These results explain
a possible failure mechanism, but do not establish that host preemption or a
busy UART caused candidate 190's runtime failures.

## Producer-to-collector backpressure finding

The host collector had a concrete way to create the observed THRE-busy state:
`tools/sercat.py` called synchronous `fsync` after every socket `recv`, in the
same thread responsible for draining QEMU's Unix socket. QEMU 10.1.2 clears
LSR.THRE when the guest writes the emulated UART. Its transmit path passes one
byte to the chardev and, when the nonblocking backend returns zero or `EAGAIN`,
leaves the transmit pending behind a writable watch. The socket chardev writes
through its nonblocking I/O channel. Therefore a filesystem-sync stall in the
collector can stop socket draining, fill the bounded socket path, and keep
THRE clear until the guest's independent byte timeout fires.

Primary source:

- QEMU 10.1.2 `hw/char/serial.c`, `serial_xmit` and
  `serial_ioport_write`: https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/hw/char/serial.c
- QEMU 10.1.2 `chardev/char-socket.c`, `tcp_chr_write`:
  https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/chardev/char-socket.c

The frozen byte counts are consistent with that mechanism. Snapshots 0 through
3 completed after emitting approximately 0.5, 7.7, 7.9, and 7.7 KiB. Each
failed attempt 4 through 12 emitted a similar 35.8--41.4 KiB before reporting
transmission failure. This consistency supports a recurring finite-buffer or
writeback boundary; it does not establish the duration or cause of any
particular host stall.

The bounded correction keeps socket receive and unbuffered file writes in the
collector's main thread and moves `fsync` to one coalescing worker. A generation
counter requires another sync for bytes written during an in-progress sync,
and socket EOF waits up to ten seconds for the last written generation to become
durable. A short file write is completed explicitly; socket, write, and `fsync`
errors are nonzero collector failures. Readiness publication is inside the same
bounded worker-cleanup path, so marker failure cannot strand it. No guest timeout,
snapshot deadline, wire byte, parser rule, or exposure budget changes. Unbuffered
file writes and asynchronous `fsync` can still contend in the kernel even without
a severe filesystem failure; separating their Python threads removes the direct
receive-loop wait but cannot prove zero writeback latency. A sync which exceeds
the ten-second collector shutdown allowance fails capture, and forced process
termination can still interrupt the final sync; this correction does not claim
absolute durability under those conditions.

## Safe next plan

Freeze candidate 190 as invalid and do not relax the replay parser or reuse its
failed recovery. Establish the UART failure boundary with the offline fixture,
review any bounded transport correction, and run the full regression before
building a fresh candidate with a fresh nonce and separately reviewed finite
authority. There have been three consecutive unresolved GPU cycles after
candidate 186. Under the latest user instruction, that three-attempt batch
requires review before another cycle; the Astra review was therefore dispatched.
Review does not increase the launch budget or relax any recovery gate.
