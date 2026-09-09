# metal-009 / candidate 1.0.176

This one-shot controlled run loaded build `ac3732d072174d2d847dacec4e9982c2` from source commit
`5792fa7abe26fceea4be42074e3323c259da5bf1` under run
`e02fbed46a6a4df4ae48d7c1d8597985`. The reviewed continuation seal and schema-7 receipt bound
the exact candidate, the candidate-175 closure evidence, and the two-entry boot-ledger preimage.
The run consumed the boot's third and final allowed launch. No retry is authorized.

Candidate 176 passed the corrected workload-readiness gate. The early BAR0 owner path, native KIQ
submissions and stamps, one-instance SDMA topology and channel remaps, engine start, and outer
accelerator power-up all succeeded. The prepared Metal probe ran. It enumerated `AMD Radeon
Navi23`, advertised Metal 3, compiled its shaders, and committed the first compute command. That
command ended with status 5 and `Internal Error (e00002bd:Internal Error)`. The local SDK maps
`e00002bd` to `kIOReturnNoMemory`. The probe completed zero command buffers and compute rounds,
checked zero values and pixels, and exited 1. Correct Metal compute and rendering remain unproven.

The classifier reports `INCONCLUSIVE / sdma_vm_program_missing`. No `sdma_vm_program`,
`vmid2_root_repair`, or page-table-walk record followed the failed command, so this run does not
establish whether the command reached the instrumented SDMA packet path or whether the VMID-2
root repair would have matched and run. The failure is a real Metal execution result, unlike
candidate 175's circular probe gate, but it does not by itself localize allocation failure to
userspace, kernel resource setup, VM programming, or GPU submission.

The guest honored the bounded shutdown request and exited. Normal recovery returned a schema-6
`recovered` record after dequeuing two MEC HQDs, retiring graphics through the temporary host KIQ,
and observing the exact completion fence `1047195047`. Final graphics pipe 0, HQD active/doorbell/
pointers, PQ polling/status/ranges, and the host-KIQ cleanup fields were zero; PAGE IB and PAGE RB
enable bits were cleared in order, and SDMA was halted and idle. No optional stopped-WPTR cleanup
was needed. The two PSP destroy commands had exact acknowledgements.

That physical cleanup result was not a validated reusable receipt at run time. The committed
schema-6 consumer rejected both the run copy and canonical receipt at `_valid_gart` because it
treats the allocator-excluded interval `[0x0f100000, 0x10000000)` as a single scratch-write hazard.
The actual descriptor and temporary-KIQ write ranges end at `0x0f113004`; the active GART table
starts at `0x0fdfc000`, so the measured writes and table are disjoint. Every other isolated receipt
predicate passed. The two JSON files parse to the same object but have different serialization and
SHA-256 values. Preserve both unchanged; a later consumer correction does not retroactively bypass
the boot ledger or authorize warm reuse.

The independent [range audit](recovery-gart-range-audit.md) confirmed the actual recovery writes
and GART table are disjoint, then narrowed only the schema-6 consumer to the descriptor span
`[0x0f000000, 0x0f000048)` and conservative host-KIQ span
`[0x0f100000, 0x0f113004)`. The corrected consumer passed 346 tests and validates both unchanged
receipt serializations with `[]`. Their hashes remain `77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180`
and `4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676`.
This validates the candidate-176 cleanup evidence under the corrected schema-6 rules. It does not
authorize another launch: the independent three-launch ceiling still returns `launch_ceiling`.

The 32 kernel messages captured during exposure contain no configured host-fault, IOMMU-fault, or
reset match. A fresh read-only postflight found no QEMU, recovery process, residual launch unit,
pending launch, or `/dev/vfio/31` holder. PCI command remained 3 with bus mastering disabled;
`reset_method` remained empty; the device remained bound to `vfio-pci`, powered `D0`, pinned on and
runtime-active with enable count zero. The exact host gate returned no error. The boot ledger is now
3/3 and has SHA-256 `0f45b2c01b5ea6863b01bc0777824d8da3c7ee7ea5d1b900616d44cd3a1c95da`.

All JSON, JSONL and serial artifacts are byte-for-byte copies of the immutable coordinator output.
The archive also preserves the one-use authorization receipt, continuation seal, canonical recovery
receipt, final ledger, pre-launch readiness record and the independent recovery/GART range audit.
The [submission forensics](submission-failure-forensics.md) pins the asynchronous failure boundary
and candidate-177 trace plan. The separate
[producer-hardening note](recovery-producer-hardening.md) records the post-run pre-consumption GART
ordering fix without attributing it to candidate 176. [SHA256SUMS](SHA256SUMS) covers every copied
artifact and all four notes.
