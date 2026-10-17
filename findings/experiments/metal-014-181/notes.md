# metal-014 / candidate 1.0.181

Run `8a6beaeb1b5f5800a7e01c1e1954c4b5`, build `4c84407175774276a104c5737f098ddd`,
source `dbc4360c8040118d6058249e59bded6164cce395` (worktree at `a751448` for the
coordinator), boot `5aa7641a-6dd5-4cb6-a482-5bd1b15fa946`, second launch on this boot
under the first policy-pinned one-run authority (`one-run-policy.json`,
`one-run-activation.json`). Candidate 180's state was retired first through the
schema-3 recovery with the terminal-prefix CR2 tolerance
(`candidate180-recovery-replay-proof.json`, `candidate180-recovery-retry.json`);
that receipt was `recovered` and authorizing.

## Functional result

`rgpuvmroot=3` routed `AMDGFX10VMM::getPDEValue` and `getPTEValue` (entry spans matched,
both routes ok). Native startup, the lease, the native VMM arena and the VMID2 root repair
repeated candidate 180 (`native=0x84b6f3000 live-match=1`). The first fault was again an
SDMA0 read under VMID 2 with `MAPPING_ERROR` at `0x400180000`
(`VM_FAULT_STATUS=0x201b3b`); later faults `0x90093a` at `0x400300000` and the page queue
stalls (`SDMA0_PAGE is occupied by channel 16 stamp 1`).

The probe ran for the first time in a warm launch and reached `commit`: it ended with
`GPU completion timeout after 5 seconds` after 18 channel submissions
(`SUB: summary ... submit=18/18/0`), no completed command buffer.

The conversion counters refute the assumed producer timing rather than the rule:
`VM: entry-conv mode=3 routes=1/1 pde=0/0/43/0/0 pte=0/0/5/301/0` classifies every
counted call as outside the MC aperture, yet a read-only BAR0 dump of the stopped device
after the run shows VMID2's root page directory (physical `0x84b6f3000`, BAR0
`0x0b6f3000`) with exactly one entry, index 0, `0x200000f40b6f4001`: the `getPDEValue`
encoding (block fragment 16 in bits 59:63, VALID) around an **unconverted** MC child
address `0xf40b6f4000`. CTX1's root at `0x0b6ff000` likewise holds `0x200000f40b700001`.
The page directory index is relative to the context start (`0x400000000`), so this is
the entry the walker consults for every faulting address; its child pointer names a
physical location outside the carve-out, which is why the leaf lookup reports
`MAPPING_ERROR`. The first arena block is the VMID2 root, so these entries are written at
VMM enable time; the wrapper's gate (marker plus aperture) evidently opened later than the
first producer calls, and only later calls were counted. Candidate 182 confirms the marker
at `AMDHWVMM::init`, samples every producer address with its domain, counts pre-gate
calls, and walks the VMID2 tables at the prepared phase.

## Capture and cleanup

The CR2 capture ended in a forced stop during replay of attempt 3; attempt 2 is a complete
164-record snapshot (`RGPU_END2 ... s=00000002 count=00a4`), attempt 3 has 37 valid,
prefix-consistent chunks and a truncated final line. Strict and terminal-prefix parsing
refuse it; the new `terminal-prefix-open` rule accepts it with no extra records and no
abort. The lifetime marker read `VALID` in the guest and in both host BAR readbacks.

Schema-3 recovery (`canonical-recovery-receipt.json`, recovery
`9e4dfa6dbf8e4309b9d38a8d64d65a39`) dequeued all three active MEC HQDs with no timeout or
forced clear, read CP status idle, destroyed both PSP rings with exact acknowledgements
and recorded no kernel message, but the temporary host KIQ did not consume graphics
`UNMAP_QUEUES` (`host KIQ wptr did not clear`), so it is `incomplete` and
`authorizes_launch=false`. The graphics ring had been left active by the faulted CP.
The ledger is 2/3; per the standing gates no further launch is admitted on this boot and
the next experiment needs a fresh host boot.

Two earlier launch attempts on this boot were refused at admission before any device
access (`v2_reuse_requires_finite_authority`, then the identity gate's lease schema);
their outputs are preserved under `run/candidate-181-refused-admission/`.
## Superseding interpretation for candidate 183 planning

Candidate 182 supersedes the earlier gate-timing explanation. Its counters and samples still saw only zero template addresses even though the native marker preceded VMM arena creation; the stopped-table MC child remains candidate 181's inherited observation. KDK disassembly established the missing boundary: `getPDEValue` and `getPTEValue` return an address-free template, while `AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr` receives the separate real address as its source operand. Candidate 183 tests conversion at that one updater boundary; it does not change the existing native initialization or allocator sequence.

Candidate 181 did not demonstrate a prepared-phase walk. Its stopped-device table inspection and conversion counters remain frozen evidence. Candidate 183 requires a returned converted child sample with the expected caller, template flags, framebuffer arithmetic, and computed composition. That proves source forwarding through the native updater, not the bytes of an SDMA packet or its execution. A mapping fault, checked workload result, and the unchanged probe remain the evidence for actual GPU execution.
