# Candidate354: observed guest shutdown and transient remaining vCPU thread

Run `0bb9177e80b4d9db4494927fd22d0796`, metal-197, build1.0.354
`46248f64ab5d476bab9a92471491cc5d`, MODE2#293, bootba51b3c6. Diagnostic
full-refresh ON image945eea90; same approved O2 presenter368a69ad. No new
capture-loss grace or completion exception.1196 host tests pass, eight skips;
expanded build-input validation and dry-run pass.354 is a lifecycle diagnostic,
not another cadence/performance measurement.

Native Metal/WindowServer/display probe pass. Actual virt-manager shows the
normal HiDPI desktop; capture frames advance, display-awake assertions verified,
source diagnostic absent. Viewer closure leaves the exact VM alive. Root requests
stop through the harness, never kills the runner or resets a running guest.

## Shutdown evidence

The callback durably records identity-bound lifecycle SHUTDOWN_GUEST (event6,
detail1) at monotonic62850.967166798 / epoch1791547858.8953152. It names the
same domain/run, namespace, original PID113/start34256195 as running/terminal
receipts. A separate read-only host `/proc` watcher, mapped to the same container
CID/StartedAt and host QEMU PID/start, samples task states at50ms intervals.
At62850.986832556 it observes only:

- original leader113, stateZ, host818150/start34256195;
- CPU0/KVM thread120, stateR, host818157/start34256199.

At62851.087395882 the original process directory is gone. This demonstrates a
transient zombie leader with a remaining vCPU thread during an eventual clean
shutdown. The watcher uses sequential reads, not an atomic snapshot, and its
sampling bounds do not give exact thread lifetime. It cannot prove that352/353's
remaining thread was the same thread or that arbitrary remaining workers are safe.
No permissions/FD ownership are inferred from the thread name or state.

Both EOF hooks subsequently see QEMU already reaped and allow natural container
exit in~0.445s. `completed_original_zombie=false`; the completed-zombie proof
branch itself is not exercised. The actual controller terminal records
reason=guest-shutdown/process_exited=true. Unlike352/353, this is a genuine
controller completion, not merely the outer exited-after-guest-request string.
Capture CORE_PROBE_PASS/earliest_failure=null; GPU recovery recovered and
`authorizes_launch=true`. VM/cycle stopped, host awake, no reboot/rebind.

The diagnostic callback succeeded before observed process disappearance, but
this native run did not retain the exact host EOF timestamp. Do not claim a
measured event-to-EOF delta. The isolated software pair did retain that ordering;
future shutdown-only waiting must bind to a recorded EOF origin and preserve the
absolute two-second budget. No blanket wait for a live process is justified.

Next test a conservative event-bound wait only when the fully validated original
leader isZ with another task and an independently observed, matching guest-shutdown
event predates EOF. Missing/stale/wrong identity/host event, unrelated capture
loss, other QEMU processes, inaccessible evidence or deadline exhaustion must
retain immediate stop. Waiting is not completion: retain actual process/FD proof
and real terminal/recovery receipts. First cover the delayed-worker and unrelated
live-capture-loss pair in isolated software, then review before native use.

[Exact receipts and task observations](libvirt-shutdown-native-evidence-20261009.json) ·
[Diagnostic design and software evidence](libvirt-shutdown-observation-plan-20261009.md) ·
[Same-image performance milestone](bochs-full-refresh-paired-20261009.md).
