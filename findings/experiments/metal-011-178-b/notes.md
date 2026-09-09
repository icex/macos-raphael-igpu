# metal-011 / candidate 1.0.178-B

Candidate 1.0.178-B used run ID `4a45f4a4c1dd49c69fab2dc37e2e4898`
and the same candidate 1.0.178 build, configuration, boot disk, probe, and
180-second VM / 45-second probe bounds as 178-A. Its separately reviewed
activation was bound to A's exact output digest, receipts, activation, and
five-row ledger. It initialized successfully from A's validated schema-6
cleanup; native KIQ, SDMA, engine, and outer accelerator startup completed.

The observation-only map-phase hooks recorded this terminal summary:

```text
SUB: summary process=178/178/178 mappings=531/531/531 prepare=534/534/534 map=531/531/531 submit=0/0/0 dropped=3484/1742
SUB: map-phase-summary total=531 capacity=0 va=0 backing-pte=531 unknown=0 dropped=0/0/529/0
```

The two retained detailed records both kept flags `0xb13` and GPU virtual
address `0x4000c0000` unchanged across the failed call. Bit 0 was set and the
GPU virtual address already existed, so the observer classifies all 531 failures
as `backing-pte`. This excludes the instrumented capacity and VA-allocation
branches for these observations, while leaving backing-resource preparation
versus PTE preparation unresolved. The finite trace dropped 3,484 ordinary and
1,742 notable records. It has no issuer/PID/run correlation, so no retained map
object can be assigned uniquely to the probe.

The probe independently enumerated `AMD Radeon Navi23`, reported Metal 3, and
compiled its shaders. Its first compute command again failed with status 5 and
`e00002bd` (`kIOReturnNoMemory`). Zero command buffers, compute rounds, values,
or render pixels completed. The archived raw verdict remains unchanged:
`INCONCLUSIVE / sdma_vm_program_missing`. The absent SDMA/VM diagnostic follows
the observed pre-submit failure and does not identify a separate SDMA defect.

The guest exited after its bounded shutdown request. Schema-6 recovery returned
`recovered` and `authorizes_launch=true`, dequeued both active MEC HQDs
(`2/2`) with zero timeout or forced clear, matched host-KIQ fence `786938751`,
and measured zero final queue activity and doorbell enables with idle CP status.
Recovery ID is
`8fb71c4acf944fa3b6ee545dfb58a448`. The raw and canonical receipts validate
and are semantically equal; fresh postflight found no configured host fault or
reset match and no remaining VM or recovery process.

The complete bounded sequence measured three cleanup-to-restart transitions:
176-to-177, 177-to-178-A, and 178-A-to-178-B. This meets the planned finite M7
transition count without reset, rebind, or host fault, but does not prove
unbounded repeatability, the historical host-hang cause, native guest teardown,
Metal execution, or desktop acceleration. The append-only ledger is terminal at
6/6 and this plan admits no seventh launch.

`SHA256SUMS` verifies the integrity of every file in this directory, including the exact
run output, canonical receipt, terminal six-row ledger, both manifests, policy,
both activations, staging evidence, and post-run validations.
