# Candidate341: valid TAP and external domain stop

## Observed

The transaction core creates a transient paused TCG domain, passes a real TAP
file descriptor through libvirt getfd, attaches the TAP backend to the precreated
hub and vmxnet3 NIC, checks the actual network topology, then resumes CPUs.

The independent software test uses a network-none Docker container with only
`/dev/net/tun` and CAP_NET_ADMIN added. A container-root helper creates rgpu_tap
in that isolated network namespace and transfers its FD to the host controller
with SCM_RIGHTS. Host and QEMU observations identify the same named interface:
TUNGETIFF on the supplied FD and iff in the QEMU process's fdinfo. The exact HMP
network report links backend rgpu_lan_backend through rgpu_lan_attachment and
hub0 to lan0/vmxnet3. No host NIC, KVM, VFIO or physical GPU is opened.

After resume, an isolated AF_PACKET sender injects a fresh60-byte experimental
Ethernet frame. The exact frame is present in QEMU's TAP filter capture. This is
backend packet delivery, not guest driver or macOS network traffic proof.

An external `virsh destroy` models the libvirt Force Off operation. Cleanup
observes domain absence and separately verifies QEMU PID/start identity exit.
Repeated cleanup succeeds without a second destroy. The test container stops
normally. The host development sleep:idle blocker remains active.

## Corrections during the test

- Docker reports CAP_NET_ADMIN, not NET_ADMIN in inspect. The initial assertion
  refused before creating a domain.
- HMP describes an inherited TAP by fd, not ifname. The verifier now follows that
  fd into the actual QEMU process's fdinfo and confirms iff=rgpu_tap. The failed
  first check cleaned up without resume.
- Adding filter-dump changes info network output. The observer is now attached
  after the paused topology checks/resume; the earlier exact-match rejection
  also cleaned up without resume. Raw events preserve these attempts.

The complete host suite passes:1,057 tests,3 skipped. This includes19
transaction failure/identity tests; counts do not establish guest functionality.

## Limits and next test

This research adapter is hard restricted to the isolated test profile. It is
not the production backend, does not validate the complete macOS command line,
and cannot claim arbitrary failed-create timeout reconciliation. Production
macvtap namespace/device provenance needs its own verification. GUI event
handling, clean guest poweroff, console disconnect/reconnect, bounded controller
exit and supervised accelerated macOS remain unqualified.

[Captured result and topology](libvirt-runtime-tap-evidence-20261009.json) ·
[Test source](libvirt-runtime-tap-smoke-20261009.py). Raw packet capture and all
attempt events: `~/macos-vm/run/c341-tap-smoke/`.
