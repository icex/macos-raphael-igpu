# Historical HDMI bring-up notes

Superseded by candidates 321–323. These are historical observations, not current launch instructions.

## HDMI inbox access — 2026-09-23

Candidate 297 detects the Samsung but reads zeros through MM_INDEX for the host-loaded
DMCUB inbox beyond the BAR. No DMUB commands were delivered. Offscreen Metal checks
pass, capture remains INVALID, and forced shutdown yielded an authorizing recovery.
The SMU answered the post-run probe. Next: validate the register-access and address
path before writing the inbox; then verify physical picture before HDMI audio.
See [live status](../status.md) for run identity and artifacts.

Candidate 298 distinguishes raw all-ones inbox reads from CGS-generated zeros;
nonzero BAR controls match both accessors. Clean guest shutdown completed, but
CR2 producer overflow (512 records, five drops) blocked recovery and reuse.
Reduce optional diagnostic volume before another launch; preserve loss gates.

Candidate 299 is built/tested but unrun: read-only aperture-boundary checks and
reduced optional CR2 logging, awaiting reboot after 298 failed recovery.

## Host DMCUB memory preservation — 2026-09-23

300 reserves the host window tail through native GMM accounting; guest TMR moves
below it and inbox reads stop returning access-denied all-ones. Old contents remain
zero after preceding unreserved runs. Clean capture, guest shutdown and recovery
pass. Next: fresh host initialization and guarded delivery.

Candidate 302 (2026-09-23) establishes reversible CPU read/write access to the
reserved host DMCUB inbox on the same host boot. The first command passed full
readback but firmware did not consume it; HDMI output remains unqualified.
Capture and guest-request shutdown completed, recovery authorizes reuse.
See [live status](../status.md).

### Same-boot recovery without a guest lease (2026-09-23)

Candidate 307's early panic was recovered on the same host boot using MODE2,
complete stable stopped-queue/SDMA scans and PSP ring teardown. The new schema-9
receipt permits one normal harness launch without borrowing an older lease.
This is a stopped, queue-free recovery result; active-queue recovery and physical
HDMI output remain separately qualified. Host regression: 1017 tests pass.

## DMCUB firmware startup — 2026-09-24

Candidate314 supersedes the stale-firmware blocker and former blanket prohibition
on guest firmware actions under explicit user authorization. Native PSP accepts
the signed payload; secure windows are checked inside the guest TMR. Startup
returns three fresh05003500 replies with zero fetch/write faults. Clean guest
shutdown and authorizing recovery follow. The desktop probe has an independent
nonfinite JSON error; no new Metal or physical-display pass is claimed. Next is
HDMI mailbox consumption. [Evidence and implementation](../findings/research/dmcub-psp-load-20260924.md).

Candidate315 additionally verifies17 consumed HDMI VBIOS commands, scanning OTG0,
HDMI enable/symbol clock and HPD. After attachment, macOS identifies the Samsung
Odyssey G95NC as online/main at3840x1080/about59Hz. Physical-screen confirmation
is pending. The core/offscreen probe, capture, guest-request shutdown and recovery
passed. A repeat uses a longer inspection window under the6000-second cap.
Historical315 had no audio passthrough. Candidate323 now passes physical HDMI audio.
