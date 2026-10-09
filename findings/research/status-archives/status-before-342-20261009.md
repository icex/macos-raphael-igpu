# Live status — 2026-10-09

## Candidate341d: accelerated desktop and input in virt-manager

Run `d37215940a6999e73b2de61e7ac573da`, metal-187, build1.0.341,
MODE2#282 on bootba51b3c6. Native libvirt paused launch, exact QEMU identity,
macvtap FD transfer and supervised resume pass. Native Metal and WindowServer
accelerator ownership pass. The actual virt-manager console renders3840×2160
pixels/1920×1080 logical; keyboard receives RGPU341 and one correctly positioned
mouse click. Bridged en2 reaches the LAN gateway with3/3 replies. A180-second
moving-material workload completes2,386 event iterations (not viewer fps).
Closing/reopening viewers retains the same VM; domain XML is unchanged.

Capture: valid CORE_PROBE_PASS, no earliest failure, accepted terminal-prefix
critical capture with a fresh quiesce acknowledgement. Outer shutdown records
exited-after-guest-request; native GPU recovery records authorizes_launch=true.
The VM/container is stopped and the development sleep:idle inhibitor remains active.
No reboot or rebind was needed.

**Remaining lifecycle defect:** critical serial EOF invokes the exact-container
stop guard before libvirt saves terminal.json. Its receipt is absent; do not claim
natural native-controller exit or complete manager lifecycle qualification.
The guard remains required. Next iteration must preserve capture-fatal cleanup
while allowing a bounded, identity-checked controller teardown. A separate manager
capabilities warning is reproduced by the inherited QEMU launcher PATH shim;
candidate342 has an offline-tested daemon discovery fix.

Driver source is unchanged from340; checked-in executable/manifest now match341.
Host suite before this run:1,104 tests pass,3 skipped. Measured console frame
delivery, host-window resize, broader lifecycle/desktop coverage and VirtualBox
remain open. The56MB Display adapter is presentation-only; macOS independently
reports2GB for AMD Radeon Navi23, the native renderer.

[Run evidence](findings/research/libvirt-native-console-20261009.md) ·
[Artifact hashes](findings/research/libvirt-native-console-evidence-20261009.json) ·
[Previous status and failed341 attempts](findings/research/status-archives/status-before-341d-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-342-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
