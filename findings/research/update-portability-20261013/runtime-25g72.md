# Native macOS 26.6 / 25G72 core rendering evidence

Candidate489 run `40f9b15bfd15c5fe9ab2641836a9901b`, build
`2164b9b5c5324ef082d715489e97b0d8`, executable SHA256
`7a70b3b2857aac9876872e3dccba703d387f1de2dcc7c507adb0e5eafd17c1c0`.
Source `0e29626659938d8675263bf843deff72e8bf1d09`, bounded card metal-284,
frozen QEMU pins v15. Native signed installer upgraded an independent tested
15.8 clone to 26.6; a fresh disk-bound GPU-less compatibility observation passed
before GPU exposure. User's original 15.8.1 disk was preserved throughout.

Function: CORE_PROBE_PASS, all 164 kernel sites resolved, hybrid and SDMA routes
active, VCN allocation extension readback verified. WindowServer accelerator
client, display on Navi23 and Metal3 all observed. Main plus two driver-only
readback matrices check 61,274,112 pixels with zero mismatches. No probe self
patching is needed. Offscreen test completes 211 frames in 3.00 seconds
(70.3fps); performance is below the macOS15 baseline and remains follow-up work.

Capture: UID501 window submits 211 frames, receives 211 presentation callbacks,
with no missing drawables or failed command buffers. Its own captures show the
correct quadrants and a moving bar at 526..605 and143..222. Presentation times
are zero, so frame timing/FPS is unqualified. Parent/root captures miss the
window pattern. A QEMU window exists, but another host application covers the
whole-screen capture; direct QEMU picture evidence is unqualified for this run.
CR2 quiesce accepts the terminal-prefix snapshot13 with450 records. Earlier
snapshot5 transmission failure does not override the accepted final capture.

Cleanup: native identity-bound request shuts down the guest; QEMU exits0.
Ordinary recovery reports recovered and authorizes_launch=true. No noqueue
fallback is needed, no host faults observed, and the device remains on
vfio-pci with power/control=on. Host suite1624 tests/8skipped passes.

Artifacts: `/home/user/macos-vm/run/candidate-489-results/` contains probe,
verdict, serial/critical captures, shutdown, recovery and exact manifest.
This verifies core rendering and moving self-capture on26.6. It does not yet
verify26.7.1, direct QEMU picture, presentation timing, full-field4K120,
physical HDMI, all codecs, fresh-boot reliability or crash recovery.
