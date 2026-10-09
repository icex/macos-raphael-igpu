# Live status — 2026-10-10 — clipboard works; USB topology investigation

Candidate421 run03771bffaa898236a0023c1de3e480a0 completed. Bidirectional
synthetic text clipboard works through native virt-manager, including Unicode and
multiline text. Host-to-guest ASCII and reconnect transfers passed. The external
427 holder compiled and kept the signed capture app unchanged; its maximum/native
mode is now3840×2160. The presenter remained running after installation and through
multiple viewer reconnects; no general resize-stability claim yet.

USB selection uses virt-manager's existing Redirect USB device dialog. The user
selected Arctis Nova7X1038:22a5. Linux interfaces were claimed and the client reports
connected, but macOS repeatedly fails enumeration behind QEMU's automatic hub.
Headset returned to Linux. Next428 tests enough direct xHCI ports to avoid that hub.

Capture: valid CORE_PROBE_PASS, separate from desktop/USB qualification. Earlier
presenter reconfiguration exit is retained; combined error does not establish its
exact cause. One overlapping guest-relay clipboard recheck is excluded as invalid.
Shutdown: exited-after-guest-request; recovery recovered, authorizes_launch=true.
Receipts: ~/macos-vm/run/candidate-421-results/. Clipboard and USB evidence:
~/macos-vm/run/c421-clipboard-*/ and c421-usb-enumeration.txt.

Published dev remains4fdd0f3 (hosted tests/build passed38000293238). Current421–427
changes remain candidate-only pending integration and completed milestone checks.
VirtualBox deferred; QEMU/virt-manager clipboard, USB, resize and usability are focus.
