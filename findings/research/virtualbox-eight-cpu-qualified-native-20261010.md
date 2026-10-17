# Candidate 406: eight-vCPU VirtualBox input and natural shutdown

Software-only VirtualBox 7.2.18 bootE, UUID
`339a6c46-92f4-4c31-b32c-80351ac14947`, source `7132cd4`.
Independent clone disks, no Raphael/VFIO device and no Metal acceleration.
This qualifies the next bounded step after 403's software desktop and forced
cleanup. It does not qualify accelerated VBox presentation.

## Functional and clock observations

The hardware owner viewed the actual desktop and Terminal evidence in
`input-awake.png`: exact marker `VBOX406_INPUT_OK`, eight CPUs, build 24G830,
and owned awake job PID 1044. UserIsActive, PreventUserIdleDisplaySleep and
PreventUserIdleSystemSleep were 1. `awake-removed.png` subsequently showed the
service absent, NO_CAFFEINATE and display/system idle assertions 0; UserIsActive
remained 1. These are independent visual observations, not inferred from VM state.

Selected actual VBox configuration reports RealTSCOffset, 4699997773 ticks/s and
eight CPUs, matching 403's clock experiment. Retained UART files contain no
panic()/panic-CPU/non-monotonic-time marker. This short run is not long-term SMP
qualification. Compared with 400, clock mode and frequency both changed; the
successful run does not isolate either variable as the sole fix.

Initial Spotlight/Keyboard Setup interactions were slow. Held key presses worked;
no input-latency qualification is claimed. PerfPowerServices visibly consumed
approximately one CPU core in the retained screenshots, including after quitting
applications. This unresolved software issue remains separate from successful
input and shutdown.

## Natural completion and ownership

Root removed the owned launchctl awake job before requesting ACPI shutdown.
`shutdown-dialog-2.png` shows the blue default Shut Down action; the retained
confirmation records Return on that visually verified dialog. There was no
Terminal background caffeinate job to block exit, unlike candidate 401.

VBox logs show ACPI S5 at 264.423506 seconds, OFF at 264.426221 and TERMINATED at
264.475659, before the 300-second controller deadline. Original result reports
poweroff, unregistered=true, one unregister attempt and no cleanup error.
Independent root verification confirms the exact UUID absent from its private
registry 15.846 seconds before the deadline. This supports natural guest shutdown,
not deadline poweroff or a rewritten reconciliation. The transient locked-session
retry branch was not exercised because unregister succeeded on its first attempt.

The automated result retains `guest_boot_qualified=false`: the controller does
not automatically judge screenshots. The separate visual/input/awake evidence
above supplies the narrower manual qualification; the original result is unchanged.

## Validation and limits

Integrated host suite passed 1474 tests with 8 skips in 56.685 seconds, retained
in `run/c406-full-suite.log`. No driver build or GPU exposure occurred for this
software run. Complete desktop acceleration, actual VBox GPU transport, sustained
SMP stability and the PerfPowerServices CPU issue remain open. The companion
manifest hashes selected original artifacts; private command/configuration logs
are excluded from publication because they can contain the SMC key.
