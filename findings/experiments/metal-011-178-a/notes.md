# metal-011 / candidate 1.0.178-A

Candidate 1.0.178-A used run ID `f103e47500ed4a06ae346df23250d95d`, build
`5908f278b80548d6b9c88e2e9a300ae5`, and the first of two separately reviewed
slots in the bounded warm-qualification plan. It initialized from candidate
177's validated schema-6 cleanup. Native KIQ, SDMA, engine, and outer
accelerator startup completed.

The observation-only map-phase hooks recorded this terminal summary:

```text
SUB: summary process=162/162/162 mappings=483/483/483 prepare=486/486/486 map=483/483/483 submit=0/0/0 dropped=3164/1582
SUB: map-phase-summary total=483 capacity=0 va=0 backing-pte=483 unknown=0 dropped=0/0/481/0
```

The two retained detailed records both kept flags `0xb13` and GPU virtual
address `0x4000c0000` unchanged across the failed call. Bit 0 was set and the
GPU virtual address already existed, so the observer classifies all 483 failures
as `backing-pte`. This rules out the instrumented capacity and VA-allocation
branches for these observations. It does not distinguish backing-resource
preparation from PTE preparation, identify an issuing PID, or bind a retained
map object one-to-one to the probe. The finite trace dropped 3,164 ordinary and
1,582 notable records.

The probe independently enumerated `AMD Radeon Navi23`, reported Metal 3, and
compiled its shaders. Its first compute command failed with status 5 and
`e00002bd` (`kIOReturnNoMemory`). Zero command buffers, compute rounds, values,
or render pixels completed. The archived raw verdict remains unchanged:
`INCONCLUSIVE / sdma_vm_program_missing`. The missing SDMA/VM diagnostic is
downstream of the observed pre-submit failure; it is not evidence of a separate
SDMA failure.

The guest exited after its bounded shutdown request. Schema-6 recovery returned
`recovered` and `authorizes_launch=true`, dequeued both active MEC HQDs
(`2/2`) with zero timeout or forced clear, matched host-KIQ fence `3779898034`,
and measured zero final queue activity and doorbell enables with idle CP status.
Recovery ID is
`0975a837f47b47389c032cdb9a3e9a14`. The raw and canonical receipts validate
and are semantically equal. Candidate 178-B subsequently initialized from this
cleanup, establishing the second measured cleanup-to-restart transition in the
current bounded sequence. It does not establish Metal execution, native guest
teardown, or routine reuse.

`SHA256SUMS` verifies the integrity of every file in this directory, including the exact
run output, canonical receipt, five-row ledger, manifests, policy, activation,
staging evidence, and post-run validation.
