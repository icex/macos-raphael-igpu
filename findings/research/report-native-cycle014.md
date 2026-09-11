# Offline audit: hybrid desktop cycle 014

This audit is read-only and uses `status.md` plus the frozen output at
`/home/bogdan/macos-vm/run/metal-030-194d-output`. No VM, device, sudo, or
implementation action was performed.

## Capture integrity and mangled serial lines

The dedicated CR2 capture is the stronger source for ordered RaphaelGPU
records. Its terminal snapshot 6 reconstructs 307 records (38,250 bytes,
1,069 chunks), with `drop=0` and `trunc=0`. The parser reports one malformed
physical line, critical.txt line 674, in incomplete snapshot 4. That line is
only a prefix (`RGPU_CR2 ... b=...`) and has no checksum-valid payload. It is
therefore transport corruption, not a driver record. Snapshot 5 is the
checksum-complete prefix used for strict forensic replay; snapshot 6 is
checksum-valid as a terminal snapshot under the reviewed terminal-prefix
tolerance.

The ordinary `serial.txt` stream has six lines where concurrent writers were
joined without a newline. These are the actual mangling sites:

* line 2149 joins the end of `VM: prepared ... words=...` to the following
  `VM: root-repair ...` record (`...00RaphaelGPU ...`).
* line 2280 joins several `VM: entry-update-sample` records, and also embeds
  three unrelated `AGDCC: Unauthorized client 'PerfPowerServices' blocked`
  messages in the middle of an entry sample.
* line 2281 joins multiple eligible entry-update samples; one is visibly cut
  as `state=returne` before the next RaphaelGPU prefix.
* line 2282 joins multiple eligible and control entry-update samples.
* line 2284 joins control entry-update samples and an unrelated
  `bufattr_get_apfs ... Only accept buf I/O` message.
* line 2287 joins three control entry-update samples and then a
  `SUB: trace seq=5 ...` record.

The last item is six physical lines (2149, 2280, 2281, 2282, 2284, 2287),
although line 2280 itself contains several concatenated records. None of
these should be parsed as complete ordinary-serial records. The corresponding
entry samples are present as independently checksummed CR2 records, so the
mangling does not invalidate the ordered driver evidence. The unrelated AGDCC,
APFS, and AppleKeyStore text is stream contention/noise at these sites; it
does not show a RaphaelGPU fault.

## What the allocator and VM-walk records establish

The route observer proves that `AMDAccelVidMemory::allocPhysical` was reached;
it does not mean every allocation succeeded. The terminal summary is:

```
SUB: backing-summary completed=7268 true=233 false=7035 dropped=7031 state=live
```

Thus 7,268 backing callbacks completed, only 233 returned true, and 7,035
returned false. The four retained samples (seq 163--166) are native false
results with unchanged fields (`pre=post`, length `0x400000`, owner
`0xffffffa241b8b600`, flags `0x1010007`). A false result demonstrates that
this backing allocation operation rejected that request. A true result would
only demonstrate that one allocation operation succeeded; it would not prove
that its enclosing memory map committed or that a probe resource was backed.
The high dropped count is observer sample saturation/accounting, not 7,031
additional allocation failures.

The map summaries show backing-PTE work was classified consistently, for
example `total=421 ... backing-pte=421 unknown=0`, while the enclosing summary
ends at `map=1034/1033/421` and `submit=1084/1084/0`. This supports heavy map
activity and rejected backing allocations, but it does not identify whether
capacity, fragmentation, ownership, or unreleased resources caused the
rejects. The prior status note's examples of requests exceeding currently
free pool remain the relevant allocator hypothesis.

The VMID-2 setup itself is coherent: root `0xf40b6f3000` is repaired to native
`0x84b6f3000`, with `prepared-match=1` and `live-match=1`; the root and level-0
table entries for `0x400100000` and `0x4000c0000` are valid and complete. The
walk for `0x400200000` reaches a level-0 leaf with `raw=0`, `V=0`, and the walk
for `0x400180080` reaches a valid leaf marked `TF=1`. These are observations
of missing/diagnostic page-table leaves, not proof of a GPU page fault: all
sampled `VM: fault` records report `status=0 addr=0`, and the later CP state
also reports `VM_FAULT_STATUS=0 addr=0`. The walks therefore support a live
PTE-population/allocator-pressure hypothesis, while leaving completion
retirement and CP stall as competing explanations.

The strongest failure boundary remains after WindowServer's initial Metal
submissions: KIQ stamps 1--3 complete, stamps 4--9 time out, and
`CP_CPC_STALLED_STAT2=0x230000` recurs. No native probe, desktop helper,
drawable receipt, or changing QEMU frame was reached. The black screen cannot
be attributed to Raphael physical output because the configured generic VMware
scanout supplied the visible path.

## Smallest discriminating next test

After the mandatory review gate is closed, use one fresh, separately authorized
GPU cycle with the same candidate/topology and a deliberately minimal Metal
submission that performs no desktop helper or drawable phase. Change only the
allocation pressure: run a single small, known-to-fit buffer/command-buffer
submission, then record (a) every `allocPhysical` true/false result with
request length and free-pool state, (b) a VMID-2 walk of that exact IB and its
completion/fence address, and (c) KIQ stamp completion plus CP stall state.

Interpretation is binary and discriminating: if the small request succeeds and
its fence completes while the same VM setup avoids the 4--9 timeout, allocator
capacity/fragmentation is implicated; if it still stalls with successful
backing and valid walks, the allocator hypothesis is weakened and the next
focus is command retirement/CP programming. If the small request is rejected,
the request/free-pool pair must be retained as the direct allocator boundary.
Do not add a PTE rewrite or alter the pool bound in that test; either would
confound the result.
