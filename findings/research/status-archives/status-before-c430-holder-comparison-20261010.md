# Live status — 2026-10-10 —120Hz prelaunch guard correction

Candidate430 attempt473eac7e5a065ff55bf9c389dda76737 reset323 succeeded, then
outer launcher refused its remaining SPICE60 guard before creating QEMU. No guest
result; wrapper INVALID/capture_loss, no recovery receipt. An unused ledger
reservation remains as failed-attempt audit, not GPU exposure. The existing
pre-systemd reservation reconciler does not cover this post-systemd guard refusal.
Retry uses the supported schema8 stopped/noqueue admission path, which checks
live host and all queue gates; no receipt is fabricated or ledger row deleted.
Fix includes outer and inner launcher coverage. Host remains awake.


Candidate428 run817dfe19b8e46522c6b350fb21dc0bd4 completed. Native X11
virt-manager clipboard passed fresh ASCII and Unicode text in both directions.
Kingston0951:1666 redirected through the GUI, enumerated as USB3 storage in macOS,
and passed two matching 1MiB read-only test reads. The user confirmed seeing it.
Arctis1038:22a5 enumerated and completed stereo output callbacks; audible output
was not tested at the user's request. Normal chooser detach restores its Linux
drivers; abrupt viewer termination did not, so crash restoration is unqualified.

Window resize requests1280×720,1101×703 and1600×900 reached the guest, with
holder/presenter running and display-awake assertions present. Wayland background
clipboard delivery was delayed; only the X11 backend is qualified by these tests.
Current virtual transport remains capped at3840×2160/60Hz. Next: standard Retina
modes through5K, fixed2× automatic window sizing,120Hz configuration and measured
capture/client cadence. Physical HDMI4K120 evidence does not measure SPICE delivery.

Capture: valid CORE_PROBE_PASS, separate from desktop/USB qualification.
Shutdown: guest_shutdown lifecycle event and exited-after-guest-request observed;
wrapper outcome capture-abort-after-request prevents clean lifecycle qualification.
Recovery: recovered, authorizes_launch=true. Kingston returned to Linux usb-storage;
Arctis interfaces restored. No GPU VM is running; development sleep inhibitor remains.
Receipts: ~/macos-vm/run/candidate-428-results/. Clipboard evidence:
~/macos-vm/run/c428-x11-tests/events.jsonl; USB read evidence:
~/macos-vm/run/c428-kingston-read-eject.json; helpers: c428-final-helpers.txt.

Candidate429 integrates the completed clipboard/USB milestone and checked-in1.0.428
binary for dev publication. Host suite passes; hosted CI remains pending.
Main unchanged. VirtualBox remains deferred. Candidate430 prepares4K/120 testing.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-430-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-430-attempt-b-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
