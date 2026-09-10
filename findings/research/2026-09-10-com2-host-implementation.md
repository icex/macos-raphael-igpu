# Dedicated COM2 host implementation

Date: 2026-09-10

## Scope

The host implementation adds the opt-in `isa-serial` transport described in
`findings/plans/2026-09-10-dedicated-critical-transport.md`. It does not create a
candidate/card, deploy into `/home/bogdan/macos-vm`, launch QEMU, access VFIO, or
authorize a GPU experiment.

`tools/critical-transport.py` is the single exact contract validator. It rejects
extra keys, type-coerced numeric values, partial objects, schema mismatch, and any
boot-argument state other than one literal `rgpucr2uart=2` when selected and no
`rgpucr2uart` token when absent. New manifests pin its source SHA-256. Historical
cards omit the transport field and retain the COM1 path.

`tools/sercat.py` accepts explicit socket, output, ready path, full CID, and
channel values while preserving legacy defaults. Dual mode publishes `<CID>
console` and `<CID> critical`; historical mode keeps its CID-only marker. Each
received byte chunk is written unbuffered and fsynced. EOF ends the collector.

`tools/vm-supervision.py` adds an explicit `--critical-serial` mode. It starts
the console and critical services under one absolute readiness deadline, records
both identities in `supervision.json`, verifies both units/PIDs/tokens, and stops
both services only in the exact-CID cleanup path. Either collector retains the
same exact-CID `ExecStopPost`. Ambient `CRITICAL_SERIAL` cannot select transport:
the supervisor forces it to `on` only for explicit dual mode and `off` otherwise.

`tools/macos-vm.sh` emits explicit index-0 COM1 and index-1 COM2 QEMU devices.
COM2 is accepted only through `CRITICAL_SERIAL=on`; it is not sourced from
arbitrary `EXTRA`. `tools/redeploy.sh` rotates/truncates both live logs and passes
the explicit supervisor flag for an opted-in run.

`tools/experiment.py` validates card/manifest symmetry, boot arguments,
supervisor mode, and the running QEMU UART topology. Dedicated runs parse and
recover only from `critical.log`; they freeze its original bytes as
`critical.txt`, freeze COM1 independently as `serial.txt`, and write both hashes.
The producer line must be one completed LF/CRLF line exactly matching
`RGPU_UART_READY v=1 b=<build-id> port=2`. A partial socket chunk remains pending;
a wrong or duplicate completed line is definitive capture loss. Recovery also
checks the producer line independently. Missing COM2 never falls back to COM1.

`tools/classify-run.py` routes manifested CR2 only through `critical.txt`. Its
narrow COM1 merge admits panic context and checks driver build identity without
feeding COM1 CR2-like noise into the replay parser. The command-line path uses
the same manifest-aware transport, producer-ready, and tolerance selection.
There is no existing shutdown/run-identity record on COM1 to merge: guarded
shutdown identity is returned by `docker exec` into `shutdown.json`, probe
`RGPU_EXIT` is captured in `probe.json`, and recovery run identity is carried by
the CR2 lease/lifetime nonce. Adding a fabricated console event would weaken
provenance, so the console-only merge remains deliberately limited to observed
driver build identity and panic lines.

## Compatibility and frozen controls

The five recovery helpers remain byte-identical:

```
3616a938db007c84ecae6048bfd83100902759a328dda92c1d5394801e2d288e  tools/vfio-recover.py
445544dd52f30cf32838472d2d248d69ea1cd3e703c8f580ecef6491238aa7d2  tools/recovery_lease_v2.py
16af9cd9b5e807a44e0e28d6b6005840b9d720c50df2ce757b820dd5d3de0398  tools/kiq-recovery-proof.py
8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61  tools/critical-replay.py
61ab64bec086d0c358a05b57f893bc6267b94d9b6f431bed100de13a9d0fbcea  tools/recovery_lifetime_v3.py
```

The GUI-183 one-use runner still rejects the changed live `experiment.py`, as its
frozen source pins require. `tests/fixtures/gui183-pinned-experiment.py` archives
the exact 134,019-byte source (SHA-256
`f7ec043ea8456f60b1ff69c4595bcaeb76bd620aee9b696e69a8790d5b038503`)
for historical proof validation. Tests reconstruct the other unchanged pinned
sources from the current tree only after checking every frozen hash, and separately
confirm the current experiment source is rejected. This has no runtime Git-history
dependency. No pin or runner was weakened.

## Verification boundary

Focused host regression: 220 tests passed. Full Python discovery passed 594 tests
with one explicit skip. Python compilation and `bash -n` passed, and `git diff
--exit-code` confirmed the five pinned recovery helpers are unchanged. The GPUless
qualification agent reported 10/10 real dual-supervisor/collector cases passing;
its detailed report is separate. The live `/home/bogdan/macos-vm/macos-vm.sh`
still awaits coordinator-reviewed deployment from `tools/macos-vm.sh`, as required
by this task's no-live-harness-mutation boundary. No macOS, KVM, VFIO, device,
sudo, build, stage, or live VM operation was performed by this implementation task.
