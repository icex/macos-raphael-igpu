# Desktop sessions without expiry — 2026-10-17

The ordinary release-519 card accidentally retained `max_seconds=6000` and
`interactive_hold_seconds=5800`. The user was copying files and expected an
ordinary desktop session that stays on. Run f5446ac413460078fe9d7cdc81942c13
stopped at 16:10 local; host suspend followed at 16:25:33, after inhibition
released. Its shutdown receipt says `exited-after-guest-request`.

A subsequent user launch, 501c3f3853567b0b2ad630e57d197fa6, was interrupted by
my stopping its deadline timer: verification correctly refused the altered
supervision state and stopped the VM. Its receipt says
`forced-after-shutdown-error`, not native shutdown. The separate postrun
MODE2/no-queue receipt reports recovered and authorizes_launch=true.

The installed card now uses an explicit unlimited, no-workload desktop mode.
There is no systemd timer, launch runtime cap or interactive-hold expiry.
The existing identity-bound direct capture hooks remain active without a
session deadline; their exit reconciliation has a separate bounded budget
that begins only when capture ends. Host-fault/capture-loss stops, DMA guard,
lease recovery and release of the session's sleep inhibition remain active.
Bounded experiment cards preserve their prior deadline contracts. User
shutdown still has bounded quiesce and shutdown cleanup operations.

Verification: host suite passed 1666 tests (8 skipped), including an unlimited
hold beyond the former deadline and two identity-bound capture services with
no timer. The real release-519 staging-card validator also accepted the card.
The installed release worktree was updated to d56f1ec; its runner, supervisor,
stager and card match the checked dev change byte-for-byte. The worktree is
clean, the installed launcher retains `--skip-tests`, and no Raphael deadline
timer is armed. Fresh stopped-device recovery with the new source reports
recovered/authorizes_launch=true in
`run/desktop-no-timeout-current-source-recovery.json` (no VM launch).
No Raphael sleep/idle blocker remains while stopped. The exFAT SSD is still
mounted on Linux. Hosted test/build CI is tracked for the final dev commit;
local checks alone do not establish a full desktop or long-duration result.
No new VM launch is performed: the user will start through the desktop.
The SSD remains mounted on Linux and no content operation, unmount or USB
handoff is part of this change.
