# SPICE and VM-manager console investigation — October 9

The unchanged1.0.336 guest driver and approved candidate338 presenter already
show the accelerated desktop through QEMU VNC. Candidate339 tests SPICE before
changing VM lifecycle ownership. This document does not qualify libvirt macOS.

Software-only tests use the pinned stock image, no KVM/VFIO device and no network.
A container-local libvirt11.9 daemon launches a transient paused TCG Bochs VM.
Host GNOME Boxes connects using a private qemu+unix session socket and libvirt's
graphics-FD forwarding. Its own console visibly renders the independent color
pattern: `~/macos-vm/run/c339-boxes-bars.png`. QMP captures pass1,094,400 exact
pixels across640×480 phase changes and800×600 resize. The test also passes with
the Bochs device supplied through qemu:commandline at the macOS profile's PCI
slot7, instead of libvirt's video device. This is transport evidence, not Metal.

The first isolated Boxes profile lacked its storage pool directory inside the
container; creating that test-only path permits connection. A first-run tutorial
was disabled only in an isolated keyfile settings backend. An isolated Xvnc
server then permits reproducible screenshots without changing the user's desktop.
No real VM registration or launch hold was changed. Software QEMUs must be stopped
before hardware admission/recovery; an active one blocked336d recovery earlier.

The installed libvirt reports virDomainQemuAttach unsupported, so it cannot simply
adopt the existing QEMU process. A container-local launch remains under study.
The existing macvtap descriptor must be transferred correctly, along with exact
CPU, device, serial and lifecycle semantics. Do not bypass the current harness
or expose the held host libvirt registration merely because SPICE works.

The next hardware experiment is metal-185, unchanged driver1.0.336, new harness
on candidate339. It selects exactly one local SPICE Unix endpoint, no VNC or GL,
and the same Bochs device/address. The viewer checks container ID, start time,
console profile and user-owned socket; it disables guest resize, clipboard,
USB redirection and separate SPICE audio. Existing USB/Pulse audio stays unchanged.
Closing the viewer leaves the harness responsible for stopping and recovering.

## Host suspend during development

KDE PowerDevil requested suspend on October8 at22:35:40 EEST. The host resumed
October9 at08:35:18 on the same bootba51b3c6. No hardware VM was running.
The rgpu-inhibit container was alive but only ran sleep infinity; logind listed
no blocking sleep/idle inhibitor. A user service rgpu-work-awake now holds a
verified systemd-inhibit sleep:idle block across development, not only GPU runs.
The GPU remains vfio-pci, power/control=on, runtime_status=active. These checks
are not a substitute for the next cycle's normal MODE2 and admission checks.
