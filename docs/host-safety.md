# Host safety

Passing this iGPU through has hard-hung the host. These rules are what has kept it alive.
None of them is optional, and no finite test can guarantee the host will never hang.

## The device

**Pin `power/control=on` before anything opens the device.** Opening a runtime-suspended device
with vfio-pci hits `vfio_pci_core_runtime_resume -> down_write` on kernel 7.2.x and NULL-derefs
the host kernel. It presents as a *guest* hang — QEMU becomes a zombie, the container still
reports "Up", the guest emits zero serial bytes — and it is unrecoverable without a reboot,
because `power/runtime_status` sticks at `resuming` and anything needing the device's PM lock
blocks uninterruptibly. `tools/gpu-bind.sh` does this, and a udev rule enforces it at boot.

**The iGPU must have been initialised by `amdgpu` during the current boot** before it is bound to
vfio-pci. Early VFIO binding is refused; the former virgin-device override was removed.

**Never cycle vfio-pci → amdgpu → vfio-pci within a boot.** Once the device is on vfio-pci it
stays there until the next reboot. To reuse it within a boot, reset it in place:

```sh
tools/smu-mode2-reset.py --probe   --output ~/macos-vm/run/mode2-probe-N.json
tools/smu-mode2-reset.py --execute --output ~/macos-vm/run/mode2-reset-N.json
```

A reset counts as clean only when the receipt shows `CP_STAT=0` and `RLC_CNTL=0`. `tools/cycle.py`
does this automatically and refuses to continue otherwise.

## No sudo

The normal test path requires no root. Sleep inhibition runs as a user-level
`systemd-inhibit --what=sleep:idle` process, and an inhibitor container must be up for the duration of
a run. The container alone is not proof of inhibition: logind must report both
`sleep` and `idle` in a block inhibitor. The desktop launcher owns both the
container and a logind blocker from startup through shutdown/recovery. It stops
the container and releases inhibition on completion or startup failure. The
container uses `restart=no`; it must not start at host boot or stay up between
desktop sessions. The closed VM must leave host sleep available.

An additional user-session blocker across builds and between cycles is only
for an explicitly requested awake development session, not ordinary desktop use.
Root-only actions go through the user or a privileged container, never silently.

For an explicitly requested awake development session, start a user-scoped blocker
before builds and retain it between cycles:

```sh
systemd-run --user --unit=rgpu-work-awake --collect \
  systemd-inhibit --what=sleep:idle --mode=block \
  --who=Raphael-development --why='Active GPU development and testing' sleep infinity
systemd-inhibit --list
```

Verify the existing service instead of starting it twice. Release it with
`systemctl --user stop rgpu-work-awake` only when development no longer needs the
host awake. This does not disable the experiment's independent stop deadline.

## Supervision

Launch, serial capture and the stop deadline are owned by user systemd services:

- The deadline targets the full container ID and includes startup time.
- Experiment GPU runs require a positive exposure cap. The installed ordinary
  desktop mode (`session=desktop`, `startup_workload=none`, `max_seconds=0`)
  explicitly has no session deadline, systemd expiry or automatic shutdown.
  Its launch carries explicit desktop authority; zero alone does not admit an
  unbounded GPU experiment. Capture, identity, host-fault and cleanup guards
  remain active.
- Launch failure or loss of serial capture stops that container.
- Serial capture holds an idle/sleep inhibitor for the VM's lifetime.
- Supervision owns the entire container ID and stops bounded experiments at their original deadline. Do not restart
  a supervised container concurrently — start a new experiment with a new container ID.

## Shutting the guest down

macOS **ignores ACPI powerdown**. `system_powerdown` arrives as a power-*button* event: on a
sleeping guest it merely wakes it, and on an awake guest it raises a confirmation dialog nobody
can click. So

```sh
python3 -B tools/vm-supervision.py shutdown --state ~/macos-vm/run/supervision.json
```

requests the ACPI powerdown, waits out its grace, and then force-stops — the outcome is normally
`{"outcome": "forced"}`. APFS is journaled and replays, but this is not a clean shutdown. A clean shutdown is requested inside the guest: either through the desktop or the
identity-bound guest shutdown agent used by the experiment harness. Recent runs
record `exited-after-guest-request`; the standalone ACPI fallback described above
must not be reported as a clean shutdown.

A standalone request rejects a stale `StartedAt`, so it cannot act on a restarted container.

## Guest sleep

The guest sleeps aggressively and a lost Screen Sharing session is usually sleep, not a crash —
the serial log shows `AMDHardware::powerOff` → `ACPI SLEEP` → `acpi_sleep_kernel`. Resume it from
the host with the QEMU monitor inside the container:

```sh
docker exec -i macos-sequoia python3 -c \
  "import socket;s=socket.socket(socket.AF_UNIX);s.connect('/run/vm/monitor.sock');s.send(b'system_wakeup\n')"
```

The GPU resumes cleanly (`AMDGraphicsAccelerator::powerUpHW -> 0`, SDMA held at `0x42`). To stop
it happening, disable sleep inside the guest: `sudo pmset -a sleep 0 displaysleep 0 disablesleep 1`.

## Recovery

**2026-10-15: guard IH and GC/SDMA before guest-memory release.** The corruption
investigation found display IH records in host data and in the earlier TCG core,
with the unowned IH ring advancing after QEMU exit. Candidate 515's independent
guard retains the VFIO descriptor outside QEMU, stops IH/display and GC/SDMA
inputs, and requires stationary/idle samples before QEMU can unmap. It also
survived an exact QEMU/container PID1 SIGKILL. Ordinary recovery cannot retire
the guard-halted active HQDs and returns incomplete; the supervised wrapper
then uses a separate MODE2/no-queue recovery with complete inactive scans for
same-boot reuse. Never treat the ordinary incomplete receipt or the guard's
own release receipt as launch authority. See
[the investigation](../findings/research/guest-memory-corruption-20261015.md).

| Situation | Tool |
|---|---|
| after the vfio runtime-PM oops | `tools/recover-igpu.sh` |
| rootless GC/SDMA/PSP teardown and same-boot reuse receipt | `tools/vfio-recover.py` |
| rebind amdgpu ↔ vfio-pci with the PM workaround | `tools/gpu-bind.sh` |
| GPU wedged but host alive | `tools/smu-mode2-reset.py --execute` |

Crash capture and the exposure timer reduce risk and improve diagnostics. They cannot recover a
fabric or CPU lockup.

A missing guest ownership lease does not by itself establish a need to reboot.
`tools/mode2-noqueue-recover.py` provides a separate stopped-device recovery path:
MODE2, complete stable queue/SDMA inactivity checks, PSP ring teardown, and final
checks. See [running an experiment](running-an-experiment.md#recovery-when-the-guest-never-published-a-usable-lease).
It produces a distinct single-use receipt without weakening native lease recovery.

The launcher's macOS build check reads `run/guest-identity.json`, not the running guest: after a
guest OS update it does not stop a 24G830-only driver (24H32 panicked in the guest, 2026-10-12).
Gate on the live build before relying on it.

## Fresh boot and the iGPU display firmware

Boot WITHOUT `amdgpu.virtual_display` for the iGPU. At power-on the platform starts its own
DMCUB image (version 0x05000549, PSP-locked windows at the top of the carve-out); amdgpu's
display engine replaces it at boot with the Linux image (0x05003500). Candidate 483's cold
display path takes that Linux image over in the guest (stop it the Linux way, keep its secure
windows, then let PSP replace the TMR), as the console path always did. The empty state after
a host suspend/resume is accepted too.

Never launch over the platform image, running or halted (candidate 481 crashed the host at
guest accelerator power-up over it). tools/smu-mode2-reset.py writes nothing to DMCUB; it
admits only empty or the Linux image (tools/dmcub-halt.py `admit`) and refuses everything
else, including any image whose version a host-side halt erased.
