# Candidate373: bounded wait after a killed shutdown witness

Candidate370 run `5059bb80d8140ba8234bc31fb7fda4fc` produced genuine
`guest-shutdown`, `process_exited=true` and an authorizing recovery receipt, but
both capture hooks recorded **immediate-stop / CommandFailure137**, not natural
capture completion. Those original receipts remain unchanged.

## Retained chronology

UTC 2026-10-09, all times below within 14:59:36:

| Time | Observation |
| --- | --- |
| .029418 | Identity-bound guest SHUTDOWN event; monotonic72968.101271381 |
| .0337–.0339 approximately | Critical recv-reset72968.105552548; console clean EOF72968.105724999 |
| .0996 | First two `inspect-exited` commands start |
| .1586 | Both first commands exit0; hooks subsequently record eligible shutdown wait |
| .2168 | Repeat witnesses start |
| .235755 | Identity-bound libvirt STOPPED event |
| .241986 | `terminal.json` filesystem mtime; genuine terminal reports process exited |
| .2608 | Both repeat witnesses exit137 |
| .273696 | Docker daemon receives containerd task-delete |
| .467087 | Docker container die event, exit0 |
| .636410 | Container destroy event |

The Docker interval contains no kill event. This strongly supports natural
container teardown killing the exec witnesses while Docker's Running state still
briefly lagged. Exit137 alone does not establish that cause. The private controller
publishes terminal after its process-exit check, then closes the backend and exits;
container teardown can therefore interrupt an independently running exec witness.
The old capture hook inspected Running once after the failure and, if still true,
raised the error and invoked exact-CID stop.

Evidence retained without changing candidate370 receipts:

- `~/macos-vm/run/c370-capture-race-docker-events.txt`
- `~/macos-vm/run/c370-capture-race-docker-journal.txt`
- `~/macos-vm/run/c370-capture-race-capture-journal.txt`
- `~/macos-vm/run/c370-capture-race-evidence.json` (hashes, commands, terminal mtime)
- Original `candidate-370-results/` and private libvirt terminal/events remain
  authoritative. `vm-launch.log` has no timestamped witness results; its complete
  QEMU argv should not be reproduced in reports.

## Narrow software change

Only after the existing identity-bound shutdown-wait proof has passed, a repeated
witness failure137 permits polling exact CID and StartedAt for container exit.
Polling retains the original transport-observation +2s limit and the earlier
admitted/outer deadline. No new witness or fresh timeout resets that budget.

If the container stops, record the existing distinct
`container-stopped-during-shutdown-wait` outcome and `witness_exit_code=137`.
This is container-lifetime evidence, **not** a QEMU process-completion proof,
natural-capture claim, clean EOF, or synthesized terminal. An unchanged running
container at expiry, identity drift, invalid/unreachable inspection, non137
failure, or failed initial proof retains the existing exact-CID stop behavior.
No recovery/admission policy or direct-manager capture behavior changes.

## Validation and remaining work

Focused private-libvirt suite:149 tests pass. New cases cover delayed exit after137,
unchanged live container until the original EOF bound, earlier admitted deadline,
replacement StartedAt, malformed/unreachable inspection, non137 failure and137
without an initial eligible proof. These are deterministic host fixtures, not a
native rerun. Full host suite: 1280 tests pass,8 skipped (53.300s),
`~/macos-vm/run/c373-host-tests.log`.

Next native discriminator: genuine guest shutdown with the same pending-worker
window and an interrupted repeat witness. Require the new distinct container-exit
outcome, retained137, original budget, genuine terminal and independent recovery.
Do not retroactively relabel candidate370's capture receipts.
