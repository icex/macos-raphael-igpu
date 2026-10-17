# Candidate 190 recovery admission audit

Candidate 190's failed CR2 capture does not certify the run verdict, but it does
contain enough checksum-valid, run-bound material to serve as a recovery-only
lease seed. This must never make the verdict valid or directly authorize a
launch.

## Frozen evidence

Snapshots 4 through 12 each independently reconstruct the same three recovery
records: record 43 is `XH2 OWNED`, record 65 is `XH2 POOL state=ACTIVE`, and
record 66 is `XH3 LIFETIME state=VALID`. Their nonce is candidate 190's run ID
in the guest wire order, and their geometry and checksums are identical across
all nine occurrences. Snapshot 13 is truncated before these records. No
checksum-valid reconstructed recovery record or direct serial diagnostic says
`ABORT`.

The existing `terminal-prefix-open` recovery path rejects this evidence before
opening VFIO because snapshots 4 through 12 extend beyond the last complete
snapshot, snapshot 3. That rule is appropriate for classification: unknown
records prevent a valid run verdict. It is unnecessarily coupled to recovery,
whose schema-3 authority is the persistent BAR state rather than a complete
diagnostic snapshot.

## Safety contract

`authenticate_v3_host_kiq_lease` already compares the exact OWNED bytes from
the lease seed with VRAM, requires the exact ACTIVE pool record, validates the
persistent VALID lifetime marker and its bindings, and repeats this
authentication before the first scratch write. Recovery then retains all host,
queue, CP, SDMA, reset, journal, receipt, latest-run, and same-boot gates.

A successful VALID publication necessarily acquired the cached BAR mapping.
`establishBarMapping` returns that cached address before checking later owner
pointers. Every late abort callsite invalidates the CPU lease before returning
or suppressing follow-on client work, and the durable transition writes and
reads back `ABORTING` before changing the marker body. The existing recovery
contract assumes meaningful BAR reads and writes; hypothetical physical write
failure is not a demonstrated software-ordering defect.

Native teardown does not contradict the candidate 190 evidence. X6000
`AMDHWVMM::setVirtualSpaceReady(false)` branches at `0x578da` to `0x57913`,
zeroes `eax`, stores zero to VMM `+0x50` at `0x57915`, and returns without an
allocator call or BAR write. The AMDHWMemory virtual-space-ready method at
`0x52c3a` is a no-op. The longer VMM allocation-disable branch at `0x57a7b`
still merits a prospective binary audit, but candidate 190's only observed
allocation-disable call precedes OWNED, ACTIVE, and VALID publication.

## Recovery-only extractor design

The extractor must pin the manifest, `critical.txt`, `serial.txt`, failed
recovery, verdict, its own source, and the current replay/recovery helpers. It
must decode only checksum-valid chunks and preserve every corrupt line,
incomplete record, and incomplete snapshot in its immutable proof. It accepts
the three records only when every complete occurrence is byte-identical, the
OWNED and ACTIVE records pass the existing run-ID and checksum parser, and the
VALID record exactly derives from those bytes. Any complete conflicting
recovery record, XH2/XH3 abort, or partially reconstructed record whose decoded
prefix identifies it as XH2/XH3 is fatal. Corrupt chunks are retained as
unknown evidence and never used as proof.

Execution must require the reviewed proof SHA-256, write an immutable attempt
marker before hardware access, and allow one result only. It passes the parsed
lease seed to the unchanged schema-3 recovery implementation. The original
`recovery.json`, verdict, captures, ledger, budget, and candidate 188 receipt
remain untouched. Root and independent review are required before execution.

The live inputs still missing are a fresh same-boot/latest-ledger/no-existing-
receipt check; no active VM; exact VFIO device, accessibility, reset-method,
watchdog, and inhibitor state; the twice-authenticated BAR records; complete
stopped queue/CP/SDMA cleanup; and an unchanged kernel-fault/reset journal.
Those inputs cannot be supplied offline.
