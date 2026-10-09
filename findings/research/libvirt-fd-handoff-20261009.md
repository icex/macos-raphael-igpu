# Libvirt descriptor handoff investigation

Candidate341 starts from fetched dev73e4663. No physical GPU experiment is run.
The isolated network-none, no-device, unprivileged c339 libvirt container runs
only a paused TCG software guest. Host libvirt12.7 forwards a descriptor over its
private Unix connection to container libvirt11.9 and stock QEMU10.1.2.

`libvirt-fd-smoke-20261009.py` passes a fresh64-byte memfd through
`virsh qemu-monitor-command --pass-fds` to QMP add-fd, checks query-fdsets,
and independently reads those exact bytes through QEMU's /proc descriptor.
QMP remove-fd removes the set. The software container is stopped afterwards.
This validates the descriptor transport, not a TAP backend, network traffic,
macOS initialization, GPU ownership or VM-manager shutdown handling.

Artifact: ~/macos-vm/run/c341-libvirt-fd-result.json
SHA256: 01469f4632175db84f4b7379e19872df842bca3248a7821bdac2614104328a72

The general create/start --pass-fds API is documented for container guests only,
so do not assume it transfers the current fd3 directly into a QEMU launch.
The supported QEMU monitor API can transfer FDs after a paused launch. Next test:
use getfd and netdev_add with an isolated socket-backed network to verify
consumption and cleanup without opening the host's real macvtap node. A later
hardware profile must retain paused-before-configuration behavior, exact NIC/PCI
identity, bounded supervision, and a single owner for shutdown and recovery.

Sources:
- https://libvirt.org/html/libvirt-libvirt-domain.html#virDomainCreateXMLWithFiles
- https://libvirt.org/html/libvirt-libvirt-qemu.html#virDomainQemuMonitorCommandWithFiles
- Local QEMU source: ui/spice-input.c confirms the SPICE tablet uses the ordinary
  QEMU absolute input path. Candidate340's HMP info spice reports client mouse
  mode and info mice selects QEMU HID Tablet; no agent-mouse override was needed.
