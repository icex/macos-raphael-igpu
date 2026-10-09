# Candidate343: native libvirt terminal receipt preserved

Run `6b0f22ab5a91cb3a3cf51404e4f0459b`, metal-189, build1.0.343,
MODE2#284 on boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Build source `d411c72c51ba43f0161f792232344a3b59d448a7`, build ID
`f9c487b7e57d4983ab96b0e61dfe508e`, executable SHA-256
`a8a54591b057297a48e50ddafd7fe1a9c6b7c50e921f75437dd49f981353a74d`.

## Discriminating change

Candidate342 lost the native controller terminal receipt while outer capture,
guest-request shutdown and GPU recovery passed. The production-shaped software
pair reproduced strict process inspection failing on the unused container SSH
helper's privilege-transition process. Candidate343 omits that helper only for
the libvirt profile and adds bounded refusal diagnostics. It keeps the same
native driver source, process visibility checks, exact container binding,
original exposure deadline and immediate-stop behavior when QEMU is alive.
[Software reproduction and negative control](libvirt-ssh-shape-20261009.md).

## Native observations

The paused identity/network handoff and native desktop Metal probe pass.
`AMD Radeon Navi23` owns WindowServer and the display; the probe completes one
command buffer and checks one value. The actual virt-manager5.1.0 window shows
the normal macOS desktop. This run is a lifecycle check, not a new performance
or broad visual qualification. Guest assertions include UserIsActive=1 and
PreventUserIdleDisplaySleep=1 with a6000-second caffeinate process.

Guest port50922 still returns `SSH-2.0-OpenSSH_9.9`; the container has no sshd/sudo
processes. This verifies the SSH service route, not a fresh authenticated login.
Closing the viewer leaves the same container running. System Information again
reports native renderer2GB and virtual presentation adapter56MB; its nominal
mode metadata does not measure console delivery frequency.

The hardware owner touches the harness stop-requested file. Both capture EOF
handlers independently prove the original QEMU process has exited and record
`deferred=true`, `natural-container-exit`, about0.454seconds. The actual native
controller writes terminal.json: reason `guest-shutdown`, process_exited=true,
bound to QEMU PID113/start33410498, the original namespace, run and container.
The outer shutdown reports `exited-after-guest-request`; capture is valid
CORE_PROBE_PASS with no earliest failure. Native GPU recovery reports recovered,
authorizes_launch=true. The VM and cycle runner are stopped; the host development
sleep:idle inhibitor remains active. No reboot or rebind was needed.

This closes the missing-terminal-receipt blocker for one native guest shutdown.
It does not qualify native panic, forced QEMU closure, capture-loss repetition,
independent host boots or every future shutdown. Candidate342's hidden refusal
cannot be reconstructed retrospectively, even though the paired software test
and this native change support the diagnosis.

## Validation and next work

Final integrated host suite:1136 tests pass,3 skipped. Dry run and build identity
checks pass. The checked-in executable and manifest match this hardware-tested
build. [Raw artifact paths and hashes](libvirt-native-terminal-evidence-20261009.json).

Next isolate nongl SPICE refresh scheduling and incomplete framebuffer updates
in software before changing the native presentation path. Candidate342's sampled
29.82/18.50updates/s and partial tokens remain the current cadence evidence;
candidate343 makes no performance improvement claim. Window resize, broader
application testing and crash/independent-boot lifecycle coverage remain open.
