# Candidate345 refresh admission and libvirt conversion

The exact `CONSOLE_REFRESH=60` profile now binds its requested rate to the
admission receipt. New receipts explicitly carry `console_refresh`; historical
receipts lacking that field mean `default`, never60. The container checks the
native SPICE option against this expectation before libvirtd/QEMU creation, and
independent paused/running/exited inspection repeats the same binding. Unknown
types/rates and default/60 mismatches refuse. The supervisor explicitly forwards
the option into its systemd service. Focused libvirt suite:94 tests pass.

A conversion-only container using new native-compatible image
`sha256:6a18a413394dfca0f3882b9df722fb9f85b1126b368ffb51eb06f2bc217ffc74`
proves libvirt11.9 emits its single owned SPICE socket configuration followed by
exactly `-spice max-refresh-rate=60` for the selected profile. Default emits no
supplement. Both pass the independent full argument verifier. All fixture SMC
bytes are literal `x`; no real machine secret was read.

The container has networknone, no devices, no capabilities and no KVM/GPU.
Consequently unmodified domain type=kvm conversion is rejected by libvirt.
The successful proof preserves production XML separately and converts an
explicit type=qemu projection. For comparison only, generated `-accel tcg` is
projected to kvm, inactive domain ID-1 to1, and the unconnected monitor pathname
to a placeholder FD27. Every remaining argument is compared exactly. This is
**not** liveKVM, domain lifecycle, effective refresh cadence or guest evidence.
No domain was created; the container exited0 normally. Failed setup attempts are
retained with stopped-container receipts.

Supplement merge semantics are source-supported: QEMU10.1.2
`ui/spice-core.c:qemu_spice_opts` sets `merge_lists=true`;
`util/qemu-option.c:qemu_opts_create` then reuses the existing unnamed option
group. The native runtime must still prove the exact command and measured effect;
the conversion alone does not prove live merged-option behavior.

Reproduce with `python3 findings/research/libvirt-refresh-argv-smoke-20261009.py`.
Artifacts: `~/macos-vm/run/c345-refresh-argv-4d9d2508`, with hashes and isolated
container receipt in the adjacent evidence JSON. No production container or
hardware was touched by this validation.


## Bounded merged-option runtime check

A separate container in the same pinned image now runs QEMU with machine none,
TCG, `-S -nodefaults -display none -nic none`, and the two exact SPICE arguments
emitted by libvirt (including compression off/seamless migration). Observed
`/proc/PID/cmdline` matches the retained argv exactly. QMP `query-spice` reports
enabled=true at `/run/vm/console-spice.sock`; `/proc/net/unix` contains exactly
one listener for that path. KVM is disabled, status=prelaunch/running=false,
and `query-cpus-fast` returns an empty list. QMP quit produces QEMU exit0;
the isolated container also exits0 naturally. No CPU, guest, GPU or host network
device executes or is passed through.

This proves actual merged-server startup with the supplemental option, not
rendered cadence, Metal, a native guest or the full libvirt lifecycle. Retained
artifacts: `~/macos-vm/run/c345-refresh-argv-4a5460a9`; hashes and cleanup receipts
are appended to the evidence JSON. Reproduce with the same script plus `runtime`.
No tools/tests changed for this final runtime check.
