# Candidate341: paused libvirt transaction failure tests

The new transaction core has no standalone launch CLI and is not yet connected
to the GPU harness. It requires an injected backend to supply observed identity,
actual configuration, network attachment and process-exit evidence. Production
backend implementation, inherited macvtap provenance, bounded event handling and
full generated-command validation remain open.

## Real software VM observations

`libvirt-runtime-failure-smoke-20261009.py` ran three transient TCG domains in a
network-none, unprivileged container without device mappings. Each preserved the
zero hardware UUID and pinned run metadata plus host PID/start ticks.

- Passing `/dev/null` through libvirt getfd succeeded; QEMU refused netdev_add
  with `Unable to query TUNGETIFF ... Inappropriate ioctl for device`.
- Injected loss of a successful create reply reconciled the created process.
- Injected loss of the first snapshot reconciled the created process.

All three cases destroyed the identified QEMU process without a resume attempt.
Domain absence and process exit were checked separately. The container then
stopped normally. This adapter injects errors after known successful creation;
it does not prove reconciliation of arbitrary production timeouts. These tests
exercise no valid TAP, external network, KVM, VFIO, macOS or GPU cleanup path.

The first smoke assertion expected the word TAP in QEMU's error; the actual error
names TUNGETIFF. Cleanup had already succeeded. The corrected assertion and all
three cases pass. Raw events retain that first attempt.

## Transaction behavior

Failed durable logging cannot skip owned-process cleanup. A stopped process and
a durably written terminal receipt are separate states, so a receipt can be
retried without destroying twice. A lost cont reply records resume_attempted,
which must not be interpreted as proof of no guest execution. Create and resume
are each single-attempt operations. Replacements with different PID/start ticks
are never stopped by name alone. Mock-based tests cover these branches; they do
not establish a production backend or real network delivery.

Evidence: [captured result](libvirt-runtime-failure-evidence-20261009.json),
`~/macos-vm/run/c341-runtime-smoke/events.jsonl`,
`~/macos-vm/run/c341-runtime-host-tests.log`.

Next discriminator: attach a valid TAP in an isolated network namespace, verify
its backend/hub/fixed NIC connection before resume, then exercise manager Force
Off, guest poweroff, viewer disconnect/reconnect and the bounded outer controller.
Only after that should this profile enter the existing supervised GPU harness.
