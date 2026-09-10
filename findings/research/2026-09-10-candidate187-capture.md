# Candidate 187 CR2 capture diagnosis (offline)

Scope: frozen run `/home/bogdan/macos-vm/run/metal-020-187` only. No VM,
device, sudo, MMIO, reset, recovery, or implementation action was performed.

## Finding

The CR2 producer is emitting incomplete physical transport lines and then
starting a new snapshot. This is not evidence that the newly enlarged VM
diagnostic records are truncated in `criticalRecords`, and the dedicated COM2
capture does not show interleaving. The recovery gate correctly refuses the
capture; it must not be relaxed or used to authorize another hardware run.

The earliest invalid CR2 bytes are physical line 210. Snapshot 3's END line is
terminated after:

```text
... s=00000003 first=0000 count=0016 drop=000000000\r\n
```

The `drop` field requires 16 hex digits and the rest of the manifest. Snapshot
3 otherwise contains 48 checksum-valid chunks for records 0..21, exactly the
same 22-record extent as complete snapshots 1 and 2. Therefore the first
failure precedes the later large VM diagnostics and is not explained by their
payload length.

Complete manifests exist only for snapshots 0, 1, and 2 (critical lines 60,
110, and 160). Snapshots 3..14 are attempts without a valid END. Each attempt
ends at a different point; malformed fragments occur at lines 210, 729, 956,
1189, 1411, 1645, 1853, 1982, 2090, 2323, 2525, and 2561. The last line is also
the only unterminated file tail. Serial independently records `critical COM2
snapshot N transmission failed` for every N=3..14.

Source behavior accounts for this shape. `CriticalUart::put()` marks an attempt
failed on either a 2 ms per-byte THRE wait or the snapshot deadline;
`beginSnapshot()` delimits a failed fragment before the next canonical header.
The frozen data cannot distinguish which timeout fired. Because snapshot 3
failed on its small END manifest after snapshots 1 and 2 completed with the same
record count, the evidence favors an intermittent UART-ready/write timing loss,
not the CR2 formatter's line or record bound. Record growth makes subsequent
attempts more exposed but is not the initiating defect.

The parser's reported error is a later semantic consequence. Snapshot 2 is the
terminal complete prefix with count `0x16` (22 records, 0..21). Snapshot 4 first
exceeds it at critical lines 259-260 with checksum-valid record `0x16`:

```text
VM: entry-gate init marked=1 aperture=1 mode=4
```

`terminal-prefix-open` permits only the latest open attempt to add records.
Snapshot 4 is an earlier incomplete attempt, so
`CR2 incomplete attempt exceeds the terminal prefix` is expected. Snapshot 14
is the latest open attempt but reaches only record 15 before the exposure cutoff.
No complete manifest authenticates any record added after snapshot 2.

The COM1 serial defect is separate. At serial lines 2324 and 10937 the long
`VM: fault-walk` SYSLOG ends after `timing` and the next RLOG begins without a
newline. `CRLOG` first formats independently into a 512-byte buffer for
`criticalRecords`, then invokes SYSLOG again. The source fault-walk format fits
the 511-byte record payload, so COM1 truncation does not demonstrate a truncated
CR2 record. No CR2 attempt progressed far enough to emit and authenticate that
late fault-walk record.

## Minimal discriminating offline regression

Add a fixture-driven test that reads the frozen `critical.txt` byte-for-byte and
uses the pinned `tools/critical-replay.py`. It should assert all of these facts:

1. strict parsing fails with `incomplete transport line`;
2. `terminal-prefix-open` fails with `incomplete attempt exceeds the terminal prefix`;
3. the only valid END snapshots are 0, 1, 2, with snapshot 2 count 22;
4. line 210 is the first malformed transport line and is the truncated snapshot-3 END;
5. lines 259-260 reconstruct checksum-valid snapshot-4 record 22 shown above;
6. line 2561 is an unterminated snapshot-14 fragment; and
7. no transport line exceeds the 239-byte parser bound.

This test discriminates producer-side interrupted line emission from record
formatter overflow and collector byte loss without changing parser tolerance.
A second pure C++ UART test can deterministically hold THRE low mid-END, verify
`failed()`, then re-enable THRE and verify the next `beginSnapshot()` produces a
delimiter followed by a clean new header. Any future fix should make the frozen
fixture remain invalid while a synthetic/staged capture completes with a valid
END under the intended UART timing policy.

`recovery.json` contains only status `failed` with the parser exception. There is
no recovery receipt or evidence supporting recoverability or hardware reuse.
