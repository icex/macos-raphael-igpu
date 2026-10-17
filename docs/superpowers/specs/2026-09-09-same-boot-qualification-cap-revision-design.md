# Same-boot fourth-launch qualification cap revision

Status: design only. This document does not authorize a launch, change the ledger, or weaken any
current admission gate. Activation requires explicit coordinator review and an independent safety
audit after the candidate-176 schema-6 receipt validates under the reviewed consumer and the final
candidate-177 manifest and authority bytes exist.

## Decision

Permit at most one additional same-boot launch as an explicit revision of the initial validation
ceiling from three launches to four. The fourth launch is candidate 177 and exists only to test one
warm reinitialization after candidate 176's validated normal recovery while collecting the exact
Metal no-memory and native lifecycle traces. It is recorded as the fourth ordered ledger entry. It
is not a lease outside the ledger, a reused run ID, a continuation of candidate 176, or permission
for a fifth launch.

The revision is conditionally justified because the ceiling is a conservative policy introduced
when full-engine cleanup was unproven. Candidate 176 changed that premise: its immutable schema-6
receipt proves genuine HQD dequeue, PAGE shutdown, SDMA idle, temporary-KIQ RPTR and unique-fence
completion, graphics retirement before scrub, zero final queue and doorbell state, exact PSP destroy
acknowledgements, bus mastering disabled, and no host/IOMMU/reset fault. Independent range review
also proved the GART table was disjoint from every recovery write. The corrected consumer validates
both unchanged receipt serializations with no error.

This does not prove that a fourth launch is safe or that lifecycle recovery is repeatable. It makes
one fourth launch a discriminating M7 experiment: a fresh boot would lower accumulated-state risk,
but would not test whether candidate 176's recovery permits same-boot reinitialization. The added
exposure is acceptable only if every veto below is cleared. Avoiding a reboot is a useful constraint,
not evidence for relaxing a gate.

## Immutable proof inputs

The cap-revision authority binds all of these exact inputs:

- boot ID `5d6f45d0-4384-4340-b819-7751bc26ebb3`;
- three-entry ledger preimage SHA-256
  `0f45b2c01b5ea6863b01bc0777824d8da3c7ee7ea5d1b900616d44cd3a1c95da`, including the unchanged
  ordered rows for candidates 174, 175 and 176;
- prior run ID `e02fbed46a6a4df4ae48d7c1d8597985`;
- candidate-176 canonical schema-6 receipt SHA-256
  `4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676`, recovery ID
  `11602bc7c6f84c75afb1f2cb617a319c`, and run-copy SHA-256
  `77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180`;
- recovery/GART audit SHA-256
  `a6ad51f95e3608f47afd951f970c3f4ed849db8ad0e0aee225790c1d26875ae2`;
- historical intermediate corrected-consumer source hash
  `055e44ca0cd7c06e37a98739ccbed67e3b0578c4416c7e24fb90f2b3db0929be`, whose 346-test run first
  validated both immutable candidate-176 receipts, plus final candidate-177 coordinator SHA-256
  `937492cce4b57a9f544513c1086154e24484e02b191cf5e5e4f2ead71a7dde7e` and its complete passing
  test evidence;
- historical recovery producer SHA-256
  `8ff51636013da702fed170933ef69f62ae15bbf91d1e59011dc140b9782ee39d`, which produced the immutable
  candidate-176 receipt;
- final candidate-177 descriptor-preflight-hardened recovery producer SHA-256
  `1212c60b706f1c55b688bd45ba97fc28f28b75c08c996275041c1a7b71983453`, which must never be
  attributed to candidate 176;
- a prepared candidate-177 manifest whose exact source commit/tree, build, binary, Info.plist,
  config, boot disk, image, harness, probe, boot ID, unique run ID and 180-second limit are all
  included in the authority after they exist;
- a fresh read-only host proof taken from candidate 176's recovery-ending journal cursor.

The candidate-177 manifest is created first. The authority is then created as a write-once reviewed
artifact that binds that exact manifest and the final producer and consumer source hashes. This
ordering has no source-hash cycle: neither source file embeds the authority hash. The authority's
own SHA-256 is supplied out of band by both the coordinator and independent auditor. It explicitly
says `from_max_launches=3`,
`to_max_launches=4`, `additional_launches=1`, `automatic_extension=false`, names candidate 177's
exact manifest and run ID, and states the sole purpose `m7-normal-recovery-qualification`. Admission
accepts that exact artifact once; the atomic ledger transition records its consumption before the
launch reservation becomes usable. A consumed, changed or differently located authority refuses.

## Ledger transition

Reservation of candidate 177 performs one atomic schema transition. The preimage must be the exact
three-entry ledger above. The new ledger records:

- `schema=3`, `initial_max_launches=3`, and `max_launches=4`;
- the three existing launch objects unchanged and in the same order;
- one cap-revision record containing the authority hash, preimage hash, 3-to-4 transition, reason,
  and `additional_launches=1`;
- one appended fourth launch object containing candidate 177's unique run ID, reservation time,
  candidate-176 prior run ID and recovery ID, the cap-revision authority hash, and an explicit
  qualification marker.

The transition never deletes, rewrites, renumbers or reinterprets an earlier launch row. The exact
three-entry preimage remains archived, and every historical receipt remains byte-immutable. The
updated file is published only after full validation and immediately before VFIO exposure, using
the existing lock, write/flush, atomic replace and directory-fsync pattern. Any byte change between
review and reservation refuses the transition.

Admission after the transition treats four as an absolute ceiling. Candidate 177's cleanup may
produce a receipt for evidence, but neither that receipt nor any later cap-revision artifact can
authorize a fifth launch automatically. Supporting another launch would require a new design and
another explicit policy review; this design supplies no generic extension mechanism.

## Fail-closed gates and vetoes

All existing identity, host, journal, timeout, shutdown and recovery gates remain. The revision is
vetoed if any of the following is true:

1. Either immutable candidate-176 receipt fails the reviewed schema-6 consumer, the receipt hashes
   differ, or the range audit and consumer/producer range pins disagree.
2. Recovery still consumes the descriptor before deriving the live GART and rejecting a descriptor
   overlap. Candidate 176 was disjoint, but candidate 177's placement is not assumed; producer
   ordering needs its own fake-transport test and review before this launch.
3. The boot ID, exact ledger preimage, ordered history, prior run/recovery ID, reviewed source hashes,
   candidate-177 manifest, or cap-revision authority differs at admission or reservation.
4. A VM, QEMU/recovery process, launch unit, pending reservation or VFIO group holder exists; PCI
   bus mastering is enabled; `reset_method` is nonempty; power/runtime state, exact siblings,
   inhibitor, watchdogs or capture durability differ; or any new kernel fault/reset message appears.
   Immediately before reservation, the journal scan starts at candidate 176's immutable
   `kernel_cursor_after`, must find no intervening fault/reset message, and returns the fresh cursor
   used to seed the continuous exposure monitor.
5. Candidate 177 includes an unreviewed functional workaround, reset, rebind, raw manual probe,
   wider device scope, longer deadline, automatic retry, or more than one behavioral/trace delta.
6. The candidate-176 guest Metal failure is represented as host stability evidence. It is a real
   status-5 `kIOReturnNoMemory` workload failure; only the host kernel/IOMMU/reset interval was clean.
7. `capture_ready` does not prove the `efi_pstore` backend plus `Storage=persistent` and
   `SyncIntervalSec=1s`, or `watchdogs_verified` does not prove watchdog, NMI watchdog and hard-lockup
   panic are all `1`. An unreadable `pstore_files=None` is reported as unknown; it is neither treated
   as empty nor resolved with a privileged read. The historical host-hang review also vetoes if the
   candidate touches a shared APU resource outside the accepted containment.
8. Coordinator review or independent adversarial audit does not explicitly approve the final
   authority bytes and exact candidate-177 manifest.

No veto can be waived at runtime. Failure before reservation leaves the 3/3 ledger unchanged.
Failure after the fourth row is reserved consumes the one additional launch even if QEMU never
reaches macOS. There is no retry.

## Candidate-177 scope and lifecycle

Candidate 177 uses the normal `experiment.py run` path with a 180-second exposure. Its single
reviewed change is bounded tracing needed to distinguish Metal allocation/resource setup, VM
programming, submission and completion, and to observe the existing native lifecycle hooks during
normal shutdown. It does not add teardown routes. The existing automatic probe runs
only after exact native startup readiness. Existing serial and kernel capture, exact-container guest
shutdown, deadline, and built-in schema-6 recovery remain in control. No manual MMIO, guest probe,
reset, restart or second attempt is permitted.

A host fault or unconfirmed stop takes the existing shortest managed path and makes the result
nonauthorizing. Full host recovery still runs and preserves its raw result after normal shutdown,
guest panic, or forced QEMU close. Native teardown observations are lifecycle evidence, while the
independent host retirement proof remains the authority for physical cleanup when native calls
cannot complete. The experiment ends with the ledger at 4/4 regardless of startup, probe, shutdown
or recovery outcome.

## Result interpretation and M7 impact

A successful candidate-177 initialization would prove one same-boot transition from candidate
176's validated cleanup. In a normal-shutdown run, observed native lifecycle hooks plus another
fully validated recovery would add one complete launch/shutdown/recovery cycle. In a panic or forced
close, host retirement can still validate physical cleanup even though native teardown cannot run.
Neither outcome by itself establishes repeatability, resolves the historical host-hang mechanism,
or enables routine no-reboot automation. M7 keeps shutdown/exit mode, native lifecycle evidence,
physical recovery validation, and subsequent initialization as distinct observations, and still
needs three successful bounded cycles before routine repeated experiments.

A failed reinitialization closes this one-launch qualification plan, but does not uniquely identify
candidate 176's recovery as the cause. A host fault, forced clear, timeout, invalid receipt, or failed
candidate-177 recovery also closes reuse. Missing native teardown is recorded according to the exit
mode and does not invalidate an independently proven host recovery. A repeated Metal
`kIOReturnNoMemory` with clean startup remains useful for M4 localization but is not an M7 pass. No
outcome under this design creates authority for launch five.
