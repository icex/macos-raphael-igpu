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
`systemd-inhibit --what=idle` process, and an inhibitor container must be up for the duration of
a run. Root-only actions go through the user or a privileged container, never silently.

## Supervision

Launch, serial capture and the stop deadline are owned by user systemd services:

- The deadline targets the full container ID and includes startup time.
- A GPU run requires a positive `RGPU_MAX_SECONDS`; zero does not disable the cap.
- Launch failure or loss of serial capture stops that container.
- Serial capture holds an idle/sleep inhibitor for the VM's lifetime.
- Supervision owns the entire container ID and stops it at its original deadline. Do not restart
  a supervised container concurrently — start a new experiment with a new container ID.

## Shutting the guest down

macOS **ignores ACPI powerdown**. `system_powerdown` arrives as a power-*button* event: on a
sleeping guest it merely wakes it, and on an awake guest it raises a confirmation dialog nobody
can click. So

```sh
python3 -B tools/vm-supervision.py shutdown --state ~/macos-vm/run/supervision.json
```

requests the ACPI powerdown, waits out its grace, and then force-stops — the outcome is normally
`{"outcome": "forced"}`. APFS is journaled and replays, but this is not a clean shutdown. The only
genuinely clean one is choosing Shut Down inside the guest.

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

| Situation | Tool |
|---|---|
| after the vfio runtime-PM oops | `tools/recover-igpu.sh` |
| rootless GC/SDMA/PSP teardown and same-boot reuse receipt | `tools/vfio-recover.py` |
| rebind amdgpu ↔ vfio-pci with the PM workaround | `tools/gpu-bind.sh` |
| GPU wedged but host alive | `tools/smu-mode2-reset.py --execute` |

Crash capture and the exposure timer reduce risk and improve diagnostics. They cannot recover a
fabric or CPU lockup.
