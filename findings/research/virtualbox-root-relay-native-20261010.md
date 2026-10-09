# Candidate 415: virtio network works; root relay refuses process admission

Completed and stopped. Source `797a550` merges the tested relay source `afe773d`
with prose-only published dev updates. BootH UUID
`189cb4d1-ca4e-48bc-86a2-557ff9ba798d` uses VMSVGA, eight CPUs,
RealTSCOffset and the opt-in virtio NAT adapter. No physical GPU or VFIO exposure.
The host relay bound only 127.0.0.1:8888. NAT is not outbound network confinement.

Root viewed a usable desktop and executed read-only commands through the owned
Terminal. `network.png` shows AppleVirtIONetwork registered/matched/active and
en3 UP/RUNNING with 10.0.2.15/24. An actual DHCP lease was not separately inspected.
`agent-awake.png` shows the system LaunchDaemon as.rgpu.agent running from
/usr/local/bin/rgpu-agent.sh, HTTP403 from the local relay, and UserIsActive,
PreventUserIdleDisplaySleep and PreventUserIdleSystemSleep assertions all at 1.
Root-agent command execution and a nonce-bound response are NOT qualified.

The process guard requires /proc/PID/exe resolution. Native hardened VirtualBox
refuses this with EACCES even for the owning UID. `process-readback.json` records
PID2008371, UID1000, exact argv0 and start-time identity, EACCES on exe, and the
same PID in the owned VBox.log header. The guard therefore found no admissible
process and refused the command. There is no relay-result.txt. The next change
must bind the process through the exact owned VBox session and its log PID plus
UID/argv/start-time checks; it must not simply remove process identity checking.
This alternate evidence cannot claim kernel-verified executable identity when
/proc/exe remains inaccessible, nor does NAT nonce association authenticate a VM.

The initial interactive shell restored slowly. Root closed the clone's Activity
Monitor through Cmd-Q, then interrupted the incomplete shell startup to collect
network evidence. No latency qualification is claimed. The owned awake job was
removed and pgrep showed no caffeinate; the immediately following pmset sample
still showed its idle bits at 1, so cleared assertions are not claimed.

Root requested ACPI shutdown, viewed the confirmation dialog and pressed Return.
VBox records S5 at 286.888544 seconds, OFF at 286.894589 and TERMINATED at
286.938650, before the 300-second deadline. Original result is poweroff,
unregistered=true, one attempt, no error/cleanup_error. Later independent UUID
absence and closed TCP8888 listener were verified; that observation occurred
about 19 seconds after the deadline, not before it. No forced stop is inferred.
No panic()/non-monotonic-time marker was found in retained UART. No Metal claim.

The tested source passed 1491 host tests, eight skipped, in 56.665 seconds
(run/c415-full-suite.log). No live relay or source changes were made during the run.
