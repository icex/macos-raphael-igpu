# metal-008 / candidate 1.0.175

This controlled run loaded build `693734a021524bd29dd71df774d917a3` from source commit
`7db5a73d0ec830f31d80c4975e7a36c2f017326a` under run
`1a065e4f5f674cc0a26d4e9dbdf59649`. The early-owner repair mapped BAR0 at
`0xffffffc511a7d000`, activated the exact current-run recovery reservation, and passed PM4/KIQ
preflight. Three native `submitKIQFrame` calls and their KIQ waits succeeded. Native
`AMDHardware::powerUpHWEngines`, one-instance SDMA startup, `AMDHardware::startHWEngines`, and
`AMDGraphicsAccelerator::powerUpHW` all returned one. This confirms the candidate-174 BAR0
startup refusal is repaired on the actual device.

The Metal probe did not run. The coordinator asked the final classifier whether startup was ready,
but that classifier first required `sdma_vm_program` and `vmid2_root_repair` records which are
created only after a workload submits work. The 52 captured structured events consequently contain
no SDMA submission, VMID-2 packet program, root repair or page-table walk. The archived verdict is
`INCONCLUSIVE / sdma_vm_program_missing`; it is a harness sequencing result, not an observed SDMA
or Metal execution failure. Full Metal execution and the VMID-2 repair remain untested by this run.

The guest honored the bounded shutdown request and exited cleanly. Normal schema-5 recovery found
and dequeued two active MEC HQDs, then found graphics pipe 0 active with its doorbell enabled. Its
host-KIQ completion fence value was not observed through BAR0 and its write-pointer clear did not
read back. Either the selected HQD RPTR or the VRAM RPTR report reached `0x100`, and graphics became
inactive before scrub, but the exception path discarded the exact terminal HQD RPTR, report and
fence fields. Recovery therefore failed closed as `incomplete`, set `authorizes_launch=false`, and
did not prove graphics retirement. The final sampled ACTIVE and doorbell fields were zero after
cleanup, but those idle register values do not replace the missing UNMAP/fence proof and do not
authorize another launch. The captured recovery journal interval contains no GPU, IOMMU, reset or
host-fault message.

All JSON, JSONL and serial artifacts are byte-for-byte copies of the immutable coordinator output.
[SHA256SUMS](SHA256SUMS) records each copied artifact and these notes. The portable classifier
fixture at `../../../tests/fixtures/metal-008-175-events.jsonl` is byte-identical to the archived
`events.jsonl`; the test reconstructs structured serial records from each immutable raw payload.
It denies readiness through sequence 49, then replays the complete outer power-up through sequence
50 and the full capture through sequence 51.
