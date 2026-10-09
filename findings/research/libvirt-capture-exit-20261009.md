# Preserve native controller receipt after proven QEMU exit

Candidate341d completed desktop/Metal/input/LAN checks and the outer harness recorded a guest-request shutdown and authorizing GPU recovery. Its libvirt `terminal.json` was missing: serial EOF ran the collector's immediate Docker stop while the controller was still recording domain exit. This is not a demonstrated natural controller exit.

## Bounded correction

Only libvirt collector `ExecStopPost` now uses `vm-supervision.py capture-exit`. The independent exposure deadline remains `docker stop --time 0`; ordinary `stop_exact`, verification failures and direct-profile collector actions are unchanged. Both collectors receive fixed original CID, StartedAt, exposure deadline, run ID and admission hash in their command.

The read-only container `inspect-exited` action validates admission/module hashes/boot/deadline, plan digest, paused identity, resume permit, running receipt and current PID namespace/init start. It refuses the original process while its PID/start still exists, including unreaped zombies. It also refuses any other QEMU found by process comm or executable basename; arguments are not printed. PID1's known docker-init/tini identity is scoped by the namespace/init-start match. It never opens a libvirt connection or creates/adopts/resumes/destroys a domain.

Only that complete proof of process exit permits waiting, without sending SIGTERM, for natural container exit. The entire inspect/proof/wait allowance is at most two seconds from hook entry and is clipped by the original deadline. Missing/changed evidence, a live or replacement QEMU, permission errors, timeout, or a controller that outlives the allowance retains the immediate exact-CID stop. An independent deadline never waits for this hook. Concurrent collector hooks each retain their original bounded start; neither cancels or extends the other's stop/deadline.

A separate best-effort host receipt records the hook result. The hook never synthesizes controller `terminal.json` and never treats absence of a domain as proof of process exit. Strict proof may conservatively force-stop if EOF arrives before process reaping; no live-process grace was added.

## Validation

- Thirteen focused tests cover running/paused/permit/scope binding, forged PID, original PID still present, another QEMU, mismatched run/container/admission, proof failure, natural exit, bounded controller hang, and deadline clipping. Wiring coverage explicitly asserts the direct collector and independent deadline retain their original immediate command.
- Existing51 supervisor tests pass unchanged, including serial capture death stopping its exact container.
- Full host suite:1127 tests pass,3 skipped; `/home/bogdan/macos-vm/run/c342-capture-guard-tests.log`.
- Two paired real software tests pass under the existing entry/paused/permit/controller fixture. Actual tiny guest ACPI S5 produces serial EOF: the hook grants bounded grace, real terminal reason is `guest-shutdown`, and each container naturally exits0. Intentionally shutting the collector socket's read side while QEMU remains running produces local EOF: the proof is refused, immediate exact-CID stop occurs, container exits1, and no terminal receipt is claimed.

Artifacts: `/home/bogdan/macos-vm/run/c342-capture-exit-f49a6c30` and `...-efa31461`; [committed summary/hashes](libvirt-capture-exit-evidence-20261009.json). The first successful S5 hook took approximately0.29seconds; the live-QEMU rejection took approximately0.06seconds before invoking the existing stop path.

All software containers use the pinned image, networknone, no privilege and only `/dev/net/tun`. No GPU, KVM, host NIC or native guest disks are exposed. The fixture bootstraps TAP as root then drops to1000; its read-only Docker exec adapter explicitly chooses1000 to match the production image's `arch` user. The host invokes the real exit hook on observed EOF; systemd ExecStopPost command construction is tested separately. This does not establish native342 lifecycle success.

Preserved fixture setup failures: `...-cad2f820` lacked root for TAP initialization; `...-22e90235` retained root HOME after dropping UID; `...-25d873b5` selected root's private libvirt session for inspection. All were bounded-stopped; selected Docker cleanup receipts and stderr remain in those directories. They are test setup failures, not native VM results.

Next discriminator: a freshly admitted native342 guest-request shutdown must retain its actual terminal receipt plus unchanged strict capture and authorizing GPU recovery. No reboot or live341 daemon modification was used.
