# Candidate343: classify receipt refusal and omit unused container SSH

Candidate342 completed its native desktop/cadence run and obtained valid capture and authorizing GPU recovery, but still lacked the libvirt terminal receipt. Both capture exit hooks reported an immediate stop with generic RuntimeError. Its saved admission, plan, paused/permit/running identities and module digests agree; the missing refusal detail prevents proving342's exact runtime cause retrospectively.

## Production process-shape discrepancy

`tools/vm-entry.sh` starts the image's `enable-ssh.sh`. In the pinned image its final line is `nohup sudo /usr/bin/sshd -D &`. This leaves privilege-transition/root processes that the previous small software fixture did not have. An `arch` process cannot necessarily inspect `/proc/PID/exe` for these processes, even when the real UID is1000: the effective UID is0 and ptrace access is restricted.

The actual guest SSH route is independent: `tools/macos-vm.sh` publishes host50922 to container10022; the strict QEMU profile forwards10022 to **guest** port22. Container port22 is not published. Libvirt/harness operations use Docker exec and the private libvirt Unix socket. The repository's launcher, supervisor and profile checks show no dependency on container SSH for the libvirt profile.

The narrow fix omits `enable-ssh.sh` only for `VM_MANAGER=libvirt`. Direct/legacy profiles retain their existing behavior. No process permission or capability is relaxed; no root process is silently ignored by the exit proof. This is a source-supported dependency audit plus the isolated reproduction below, not yet a native343 lifecycle result.

## Diagnostic-only refusal reporting

The same strict exit proof now reports bounded stage/code metadata:

- admission, receipt-read, permit/plan/running binding and namespace;
- exact original PID still present, with its numeric PID and one-character process state (including zombie);
- process enumeration or scan refusal, operation, errno and numeric real/effective UID when readable;
- host container inspection versus Docker exec timeout/failure versus returned proof refusal.

No argv, exception message, paths, environment values or stderr are persisted. The host copies only allowlisted stages/codes and typed numeric/state fields. Negative helper results are structured JSON with `exited=false`; the caller still immediately stops the exact CID. All former refusal conditions, original deadline, two-second maximum grace, direct-profile behavior and stop-before-evidence ordering remain intact.

## Real software reproduction

`libvirt-ssh-shape-smoke-20261009.py` uses the same pinned image and actual entry/paused/permit/S5 fixture, with networknone and only an isolated TAP device. It uses production's default container capabilities plus NET_ADMIN for this namespace-local TAP. Bootstrap creates TAP as root then drops the controller to1000; read-only exec uses1000 to match production's `arch` image user.

Pair `/home/bogdan/macos-vm/run/c343-ssh-shape-7891c49a`:

- With the exact image SSH helper enabled, actual guest S5 reaches EOF but the proof refuses `/proc` executable inspection: stage `proc-scan`, code `permission-denied`, errno13, PID13, realUID1000/effectiveUID0. The original conservative hook force-stops the container (exit137); no terminal receipt is claimed.
- With no container SSH helper, the same guest S5 produces a valid exact-process exit proof; the container naturally exits0 and retains its actual `guest-shutdown` terminal receipt.

A separate no-SSH pair `/home/bogdan/macos-vm/run/c342-capture-exit-af8a307b`, executed using candidate343 tools, checks the negative control: deliberately lost capture while the actual QEMU PID47 remains present in stateS yields `original-process/original-pid-present`, immediate exact-CID stop, and no fabricated terminal. Its S5 case still exits naturally with a terminal receipt.

[Committed results and artifact hashes](libvirt-ssh-shape-evidence-20261009.json). The first exploratory shape run `.../c343-ssh-shape-2e79b477` also reproduced EACCES, but an assertion incorrectly expected the **real** UID to be0; it was1000. Artifacts and stopped-container cleanup receipt are preserved. Adding effective UID diagnostics resolved that evidence ambiguity.

## Checks and remaining gate

Twenty focused guard/diagnostic tests and thirteen entry tests pass. Full suite:1135 tests pass,3 skipped (`/home/bogdan/macos-vm/run/c343-offline-tests.log`). This full run preceded the root's final343 version/card preparation; rerun the final integrated suite before launch.

Next: the hardware owner must run candidate343 through the existing harness and verify actual native controller terminal receipt, strict capture and authorizing GPU recovery together. The software reproduction strongly explains342's gap but cannot reconstruct its hidden refusal or establish native success. No GPU launch, build, staging or host sudo was performed in this investigation.
