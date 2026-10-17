# Desktop inhibitor lifecycle — 2026-10-17

The installed release-519 shortcut failed twice before QEMU/VFIO exposure:
`run/raphael-macos-d20261017141242.log` and
`run/raphael-macos-d20261017141254.log` both report
`CYCLE ABORTED: idle inhibitor container 'rgpu-inhibit' is not running`.
The stopped container had `restart=unless-stopped`. No Raphael logind blocker
was active when inspected. These failed preflights consumed no GPU launch.

The repaired launcher holds a real systemd logind sleep/idle block around
the entire session, including compatibility refresh, preflight and recovery.
`desktop-inhibitor.py` starts the existing pinned helper container with
`restart=no`, stops it in a finally block, and provides systemd ExecStopPost
cleanup. A file lock and session owner prevent concurrent starts or stale
cleanup from stopping a newer session's helper. The installer includes the
helper. Guest build, QEMU image, reset, capture and recovery gates are unchanged.

Live systemd checks, without opening VFIO, used
`raphael-inhibitor-check2.service` and
`raphael-inhibitor-failure-check3.service`. While active, logind reported a
sleep:idle block and Docker reported the helper running. Termination and a
session command returning failure both left the helper stopped and no Raphael
logind blocker. An initial check exposed overlap between finally cleanup and
ExecStopPost; the final implementation waits for the lock and checks the owner.
The regression tests cover this overlap as well as stale cleanup, concurrent
starts, partial startup failure, termination and ordinary return codes.

The installed shortcut then ran the existing release 519 / metal-324 /
QEMU pins v20 on boot `aee5672f-423f-46c0-95d5-e917928b979b`:

- Attempt `d20261017141818`, run `7cb21dad101d30e43f60aeaba3e532ac`,
  build `dc14fd8203a747e1a92c8d10efdbbf94`, source `b2a0374`.
- GPU-less compatibility refresh nonce `50f25b2ea8354c468dfddc1115731590`
  sealed successfully. MODE2 reset 527 passed before exposure.
- Functional: `verdict.json` is valid / CORE_PROBE_PASS. Readback matrix
  mismatches are zero; the guest selected 5120x2880 at 120 Hz. This is the
  existing core probe, not a new full desktop or presentation qualification.
- Capture: serial (624729 bytes) and critical (978663 bytes), with identity
  and producer quiesce proof, are retained and hashed.
- Stop used the launcher's stop-requested path. `shutdown.json` records
  exited-after-guest-request. `dma-guard.json` is schema 2 / released.
  Ordinary `recovery.json` is incomplete / authorizes_launch=false;
  separate `postrun-mode2-noqueue.json` is schema 9 /
  recovered / authorizes_launch=true. `wrapper-result.json` returned 0.
- After service completion, no VM remains, `rgpu-inhibit` is exited with
  restart=no, and logind lists no Raphael blocker. GPU power/control is on.

Artifacts are under
`~/macos-vm/run/candidate-519-attempt-d20261017141818-results/` and
`~/macos-vm/run/raphael-macos-d20261017141818.log`. Host test evidence:
`~/macos-vm/run/desktop-inhibitor-host-tests-final.log`, 1661 tests,
8 skipped. Shell syntax and git whitespace checks passed.

Actual host suspend/resume was not requested or induced. The observed result
is release of the VM's sleep blocker after session completion, including on
failure. A future ordinary host suspend/resume is the separate physical
observation; this change does not claim new suspend/resume qualification.

## Ordinary desktop startup and Intel USB SSD

At the user's request, the desktop card now declares
`startup_workload=none`. Host tests remain skipped by the shortcut. Native
startup readiness, capture, the deadline, interactive supervision, producer
quiesce, shutdown and recovery still run; automatic guest Metal workloads
do not. Ordinary completed sessions are classified as
`DESKTOP_SESSION_COMPLETE`, without claiming a probe pass. Diagnostic cards
retain their default probe behavior. The launcher forwards its configured
worktree to the cycle; the installed release stays in `candidate-519`,
preserving the original build-identity path checks.

The installed ordinary session is attempt `d20261017143231`, run
`f5446ac413460078fe9d7cdc81942c13`, build unchanged at
`dc14fd8203a747e1a92c8d10efdbbf94`. Its manifest requests no startup workload;
`interactive-ready.json` exists and no `probe.json` was created. A live
snapshot is retained in `run/desktop-no-probe-live-20261017.json`.
It is left running for the user's desktop/USB use; final capture, shutdown
and recovery for this session have not yet occurred. The earlier completed
cycle above independently verifies release of inhibition after native stop.

Pre-exposure corrections did not consume GPU ledger entries. Attempt
`d20261017142715` was stopped during GPU-less compatibility refresh; the
plain guest then shut down natively. Attempts `d20261017142846` and
`d20261017143106` were refused by staging's original worktree/build-origin
checks. Those checks were retained and the updated tooling integrated into
the original release worktree. Attempt `d20261017143155` was refused because
the changed coordinator source no longer matched the previous schema-9
receipt's helper hashes. The existing no-queue recovery path requalified
the original run with current sources and unchanged ledger; its separate
authorizing receipt is `run/desktop-session-current-source-recovery.json`.
The successful ordinary launch then used normal automatic admission.

The attached Intel SSD is 1.9 TB, with an existing APFS partition behind an
ASMedia `174c:1153` USB enclosure. Its USB node initially lacked user write
access. Root-owned `/etc/udev/rules.d/70-raphael-intel-ssd.rules` now grants
uaccess only for this enclosure's vendor/product and serial; rules were
reloaded and the matching USB device retriggered through a privileged
container, without sudo. Linux had no mounted partitions on the drive.

The existing USB picker redirected the enclosure to slot 1. macOS detected
the external physical drive and encrypted APFS backup volume. The first
mount attempt waited with the volume locked. The user entered the drive
password directly in macOS. Subsequent `diskutil info` reports Mounted Yes,
Locked No, with 1.1 TB used and 773 GB available; `df` confirms the mounted
filesystem. No credentials were collected and no formatting was performed.
The console user's directory read also succeeded, recorded in
`run/intel-ssd-readable-20261017.txt`; file names and contents were not collected.
Raw disk identity/mount details stay local in
`run/intel-ssd-disk-list-20261017.txt` and
`run/intel-ssd-mounted-info-20261017.txt`.

Final local suite: `run/desktop-session-delivery-host-tests.log`, 1664 tests,
8 skipped. Ordinary-session tests verify no probe invocation while retaining
interactive supervision/quiesce, rejection outside desktop mode and a
distinct result that does not mask faults or claim a Metal pass.
