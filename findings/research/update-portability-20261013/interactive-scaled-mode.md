# Tahoe interactive scaled-mode freeze — 2026-10-13

Run dcddfb97446d76dacdfbbea0503bbc4d, candidate490, macOS26.7.1/25G241.
The user reported an unresponsive QEMU GUI. SSH/date/uptime remained responsive;
QEMU USB Tablet activity remained visible in guest power assertions.

Independent CoreGraphics mode query returned logical2048x1152, physical4096x2304,
60.000015Hz. Serial output recorded5120x2880 timing and rejected fmt10/sw27/DCC0
surfaces with4096 pitch, then zero SDMA copied frames. Output timing and source
surface geometry disagree. Earlier allocation failures are also present; their
causal role is not established. This does not prove a GPU execution hang.

The existing console-existing-mode helper was compiled with the live EDID identity
(vendor18672/product54011; its original target identity differs). CoreGraphics
session configuration selected logical1920x1080/3840x2160 at60Hz, confirmed by a
separate post-exit query. Serial published3840x2160 fmt8/pitch3840 and subsequently
103 and99 copies per10s, mean2293/2284us. QEMU visible content updated and a
pointer click dismissed App Store onboarding. The same exact display mode was
then saved through kCGConfigurePermanently; persistence after reboot is untested.

Guest and host stayed running. No shutdown/recovery result exists yet for this
interactive run. No kernel patch was installed; scaled-mode support remains open.
Raw local evidence: ~/macos-vm/run/serial.log, vm-launch.log and the immutable
candidate-490-attempt-d20261013212338-results identity/probe artifacts.
