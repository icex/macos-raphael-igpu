# metal-010 / candidate 1.0.177

This single controlled qualification loaded build `a210b5e45fe94b9cac585127aeeb22b3`
from source commit `02e527dd87c9f053e073ff359f7bf1667f397560` under run
`ff2eb6e2492a4c5c96c6c6a847ed0c26`. The reviewed cap-revision authority bound the exact
candidate-176 schema-6 cleanup, three-row ledger preimage, candidate-177 manifest and final
recovery producer. It revised that boot's policy ceiling once from three to four and appended
the fourth launch without changing the earlier rows. The final ledger is 4/4; no fifth launch
is admitted.

Candidate 177 successfully initialized from the state retired by candidate 176. BAR0 mapping,
native KIQ submissions and stamps, the one-instance SDMA topology and channel remaps,
`AMDHardware::initializeHWEngines`, engine start, and outer accelerator power-up all succeeded.
This is one measured schema-6 cleanup-to-reinitialization transition. It establishes that the
candidate-176 host retirement was sufficient for this next startup, but one transition is not
routine or repeatable lifecycle qualification.

The prepared probe enumerated `AMD Radeon Navi23`, reported Metal 3, and compiled its shaders.
Its first compute command completed with command-buffer status 5 and underlying `e00002bd`, which
the local SDK maps to `kIOReturnNoMemory`. No command buffer or compute round completed, and no
compute value or render pixel was checked. Rendering and desktop acceleration remain unproven.

The new bounded trace captures a native pre-submission failure chain. Observed
`batchMemoryMapPrepare` calls returned false; their enclosing `BatchPrepareMappings` calls made
zero of three requested mappings; `BatchPrepare` returned false; and the enclosing command queues
published `e00002bd`. This repeated across at least two queue objects and two
`IOAccelMemoryMap` objects. `submitBuffer` recorded zero entries and exits. Every observed exit was
classified notable, and the final balanced aggregate was
`process=181/181/181`, `mappings=540/540/540`, `prepare=543/543/543`,
`map=540/540/540`, and `submit=0/0/0`. This makes the no-memory result a framework resource/
mapping preparation failure before the instrumented channel submission boundary, rather than a
GPU completion error.

The trace has two important limits. Its finite normal and notable record buffers overflowed:
the final summary reports 3,608 total ordinary records with 64 retained and 3,544 dropped, plus
1,804 total notable records with 32 retained and 1,772 dropped. The independent critical replay
was complete at 158 records with zero dropped or truncated lines. Submission records carry kernel
queue/resource/map objects and thread tokens, but no guest process identity, timestamp, or probe
run ID. The probe transaction ran from 17:37:58.276 to 17:37:58.420 UTC and returned the same
`e00002bd`; every retained command-buffer exit reports that value. The shutdown-time submission
summary covers the probe interval but is aggregate, so the same path is likely rather than proven
one-to-one for the probe. These limits do not alter the observed zero `submitBuffer` count; they
prevent stronger claims about which allocation or mapping object belongs to the probe and which
exact call first caused the error.

The classifier remains strict at `INCONCLUSIVE / sdma_vm_program_missing` because no SDMA VM
program, VMID-2 root-repair, or page-table-walk record occurred. In light of the new trace, those
records are absent because the observed work did not cross the instrumented submission boundary;
their absence is not evidence that SDMA or VM programming independently failed.

The guest honored the bounded shutdown request and exited. Normal schema-6 recovery dequeued both
active MEC HQDs on the first poll, retired graphics through the temporary host KIQ, and matched
fence `688691714`. It disabled PAGE IB before PAGE RB, left SDMA halted and idle, received both PSP
destroy acknowledgements, and measured zero final graphics/HQD active state, pointers, PQ polling,
ranges and doorbell enables. Both unchanged receipt serializations parse to the same object and
validate with `[]`; their different hashes reflect serialization only.

Fresh post-run evidence found no QEMU or recovery process, residual launch unit, pending launch,
or visible `/dev/vfio/31` holder. PCI command remained 3 with bus mastering disabled,
`reset_method` remained empty, and the device stayed bound to `vfio-pci`, in D0, pinned on and
runtime-active with enable count zero. The sibling/reset-domain identity, watchdogs, persistent
capture configuration and sleep inhibitor remained exact. No kernel message or configured host
fault appeared after the recovery cursor.

All coordinator output files are byte-for-byte copies of the immutable run directory. This
archive also preserves the canonical receipt, consumed cap authority, both pre-run readiness
proofs, post-run readiness proof, candidate staging/build identity, experiment card and final
four-row ledger. [SHA256SUMS](SHA256SUMS) covers every artifact and this note.
