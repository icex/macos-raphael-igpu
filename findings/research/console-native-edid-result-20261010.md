# Candidate432: EDID mode acceptance does not supply native VBL

Attempt b runc81e8cb4dd4835f93a655a26322341fb, MODE2 reset327, build
094b096993914f959bdd0e1c32765cca. Exact GPU source remains unchanged from430.
Host suite:1536 passed,8 skipped. The first attempt refused before libvirtd/QEMU
creation because the supervisor omitted CONSOLE_EDID. The forwarding fix is
covered by the actual emitted systemd command test. Isolated b used the existing
stopped/noqueue qualification and a fresh reset; no recovery receipt was invented.

## Measured result

Native AppleBochVGAFB now lists the QEMU EDID mode2560×1440 at120Hz, including
1280×720 logical HiDPI. CGDisplaySetDisplayMode succeeds and readback matches.
The native timing helper reads this120Hz mode and CVDisplayLink's nominal period
33,333,333/1,000,000,000 seconds in the same process. CVDisplayLink creation
returns success. Thus valid EDID metadata alone is insufficient to provide the
required120Hz source clock.

The source fixture ran599 draws in20seconds after starting at1280×720/2× with
that native display ID; its nominal period was30Hz. Mode inventory before was
120Hz, but after was the saved1920×1080/85Hz mode. Both earlier long comparisons
also reverted. Their durations cannot qualify sustained120-mode output or
attribute a new30Hz regression. The immediate same-process mode/timing readback
is the clean discriminator. The cause of the saved-mode reversion remains open.

Real virt-manager screenshots show the changing fixture at1920×1080. They prove
native desktop transport works at the reverted mode, not correct sustained
1440p120 delivery. The separate source-clock test after automatic restoration
captured the CGVirtualDisplay60Hz clock and is explicitly excluded from native
results.

IORegistry captures contain no IOFBCurrentPixelClock/IOFBCurrentPixelCount timing
properties. Local decoded CoreDisplay supplies33.33ms when shared VBL timing is
missing. This is consistent with the live nominal period; the exact runtime
CoreDisplay branch has not been traced. See the source evidence in the plan.

The original holder and signed presenter were restored and verified running
before the harness stop request. Final cycle/shutdown/recovery receipts are
recorded in status.md and the evidence index.

Final capture is INCONCLUSIVE/probe_completion_missing: root guest helper preparation
was submitted before the harness finished its shared gx relay transaction.
probe.json contains the compile reply rather than the identity-bound Metal result.
This is a capture/probe failure, not evidence of a GPU regression. Future helper
preparation must wait for recorded probe completion. Shutdown request was sent,
then forced stop; recovery was recovered with authorizes_launch=true.

## Next implementation

Provide a native framebuffer timing/VBL implementation with explicit120Hz modes,
then qualify its actual display clock, Retina resize and capture delivery. Keep
the current holder available while that implementation is incomplete. The
32MiB capture limit still excludes5K;431's64MiB prototype remains offline.
Do not substitute more EDID labels for the missing timing behavior.
