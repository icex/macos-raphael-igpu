# Candidate399: host snapshot copy dominates measured commit work

Run `1849f3959a4a38e15836c9364554f76f`, launch sourcefd6dc6f0acdd52c859769ecc83384569bca7aad7, built-fromb7e17c09679eb3e78e1be9895d2d5be550a06391; build IDf868a8dae9664e469b2011390547c5ca; executable SHA256d8257d14791c7f1cee6050c250a4327cb35bde75e0bf0036c1bbc470b939ceaa. Instrumentation splits existing host snapshot work; no optimization is claimed.

## Strict timing evidence

`c399-timing-analysis.json` accepts20 independent steady4K windows8..27 for both host and guest,4691 commits each, with no parser errors. Host and guest clocks are distinct; no clock subtraction or phase alignment is inferred merely from matching window/count totals.

| Scope/stage | Weighted mean ms |
|---|---:|
| Host surface allocation |0.020582|
| Host copy including first touch |6.834006|
| Host pending free (all commits) |0.095214|
| Guest private→WC copy+fence |1.556178|
| Guest geometry MMIO |0.239862|
| Guest doorbell |6.982687|
| Guest ACK checks |1.468294|

All4691 commits have allocation/copy/free calls; pending surface was present339 times (7.23%) and null4352 times. The pending-free average is not the cost conditional on an occupied pending slot. Copy includes first-touch cost, so allocation's low mean does not isolate allocator/page-fault cost away from copying. Host-copy measurement explains most of the observed doorbell-stage magnitude; it does not yet isolate memory bandwidth, page faults, source caching or scheduling as cause. The next discriminator should preserve immutable-surface ownership while separating these costs before selecting an optimization.

## Functional/capture scope

Actual-manager4K mixed token observation in1440×900/GDK1 viewport:4036 unique IDs/100.005669s (40.3577/s), zero invalid/duplicate samples. Phase5 is a short tail and is not qualified as a complete phase. The fixture's TOKEN_DONE is retained. The final event callback was in progress (4037 started/4036 completed), so no fabricated final callback duration is included. Token-region integrity is not full-frame dynamic integrity,60Hz, GPU FPS or physical scanout. No optimization gain or regression is established by this diagnostic run.

**`c399-desktop.png` captures the wrong focused host window and is excluded as desktop evidence.** It remains hashed for the audit trail. The owned observer's RuntimeMax180 expired before the late capture; there is no verified post-workload guest-return desktop screenshot in399. No new input/audio qualification is claimed.

## Teardown and recovery

Original shutdown.json reports exited-after-guest-request with private_terminal_verified=true. Private terminal is guest-shutdown/process_exited=true. Both capture receipts say **container-stopped-during-shutdown-wait**, deferred/eventwait true, approximately0.588seconds; console cleanEOF and critical recv-reset. Do not rename those receipt outcomes natural-container-exit. Docker independently records container die0/destroy without kill/stop actions, supporting natural container completion; exec witness termination is separate from VM exit. Recovery recovered/authorizes_launch=true.

CR2 replay snapshot18/365 records retains terminal-prefix-open tolerance with zero corrupt lines and no incomplete snapshots. The CORE_PROBE verdict remains narrowly scoped. The private QEMU log is mode0600, retained outside git and **hashed only** because it contains private launch arguments; no contents are copied into this report.

The accompanying manifest hashes raw selected timing/observer/source inputs, analyzers, excluded screenshot and exact lifecycle receipts. Last delivered dev remains tested395/c1f64d0 with green hosted CI;399 is candidate diagnostic evidence. True VirtualBox software boot work remains separate.
