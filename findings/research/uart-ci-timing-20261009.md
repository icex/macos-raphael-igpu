# Software UART CI: separate protocol completion from host throughput

Dev code commit71a7f7a passes both hosted jobs in37928485421. The docs-only
successor dcf0be2 fails the positive software UART test in both attempts of
37928860285: `critical producer quiesce missed cleanup boundary` at the test's
8-second deadline. The negative ignored-token test passes. The old test discarded
its temporary captures, so those CI logs do not identify the exact transport
position at timeout. Hosted QEMU is Ubuntu8.2.2; local QEMU is11.1.1.

A bounded local discriminator runs the unchanged maximum fixture and production
collector/quiesce parser under systemd CPUQuota. No KVM, PCI or native guest is
involved. At50% of one CPU, fresh512-record ACK completes6.066s after request.
At25%, the unchanged8s boundary refuses, while the same still-running software
fixture subsequently completes a valid ACK12.402s after request. Strict replay
parsing verifies fresh snapshot0x01020305, all512 records/261632 payload bytes;
raw capture totals2287541bytes. Thus host scheduling/TCG throughput can reproduce
this failure without a protocol failure. This establishes a plausible timing
cause, not the unknowable byte position of the deleted hosted failures.

The positive test checks a fresh full snapshot, matching ACK and subsequent
silence; it has no8s throughput contract. Give that software-only positive test
30s. Preserve the negative fixture's2s boundary, its absent ACK, request cleanup
and stopped-QEMU checks. Production quiesce logic, capture, GPU recovery and run
deadlines are unchanged. Both fixtures now stop before deleting their temporary
files and optionally retain payloads, hashes and stopped-process observations;
CI uploads those artifacts even on failure. A future failure can be diagnosed
without another blind rerun.

Original controlled artifacts:
- `run/c357-quiesce-timing/timing.json` (50% CPU)
- `run/c357-quiesce-timing25/timing.json` and `vm/run/critical.log` (25% CPU)
- `run/dev-353-final-ci-failure.log` and `...-attempt2.log`

Modified positive/negative pair passes at ordinary scheduling; quarter-CPU
recheck and hosted validation are recorded in the delivery artifacts.
