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

## Socket network follow-up

The first paused-QEMU attempt to add vmxnet3 at pcie.0 slot9 refused: the root bus
does not support hotplugging. Do not assume paused CPUs make root-bus hotplug
possible. The network backend was removed and no physical device was opened.

A new software-only XML pre-creates vmxnet3 at slot9, attached to a QEMU hubport.
After paused launch, libvirt monitor getfd transfers a Unix socketpair endpoint;
netdev_add consumes that endpoint and a second hubport connects it to the NIC.
The VM is resumed only after setup. A60-byte experimental Ethernet frame sent
through the local socket is captured byte-for-byte by QEMU filter-dump before
NIC delivery. Both dynamic backend ports and the filter are removed; the whole
software container is then stopped. No host TAP/network, KVM, GPU or macOS used.

This preserves the NIC's boot-time PCI address in the software model. It does
not yet prove macOS networking, TAP descriptor use, packet throughput, or native
VM-manager lifecycle. Next: evaluate a complete libvirt launch specification with
this fixed-address pre-created NIC and single-owner teardown; do not alter the
hardware launcher based on packet transport alone.

Artifacts:
- c341-libvirt-socket-result.json SHA256 29651ecf5cd1a650f3e64f59412d6780abd704c60294e414d45c6bc6249a8a39
- c339-libvirt-smoke/c341-packet.pcap SHA256 9e84e61201b667822d39a59b0ee88de89a3c7a53f9776b99daef2d27da58c6e8
- c339-libvirt-smoke/domain-c341-hub.xml SHA256 58b3257a08bebf0b3e9f87562e5ad5b76b622bdb6a7c60bee8c4caac92bd3c34
