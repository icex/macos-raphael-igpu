# Candidate388: existing odd 1x mode selection

Run `f61db53ed51c02394163eb0ba7e08367`, metal214, driver1.0.388,
source `caab7d8`, build `95053dc30d5e479cbeec0ec58a119168`, executable SHA256
`a82d6cd0d017c2f62d3614c5f4a6e6cc7cc6ca59c9d5248e6ffe0daf0c9cfcff`.
MODE2#310; host boot prefixba51b3c6. Root owned all native operations.
The ordinary presenter was used; snapshot ownership remained unarmed.

## Scope and mode evidence

Installed support payload4d424e40 automatically starts holder617, agent759 and
presenter760. The capture application, receipt and CDHash remain unchanged.
The existing holder control adds2470×1486 physical /1235×743 logical. Its hiDPI=1
mode table exposes both that2x mode and1235×743 physical/logical1x.
Diagnostic source `ef586a2` in candidate389 explicitly selects both directions
on the same holder/presenter, with exact settled readback:
`c388-restore-two-x-v3.txt` and `c388-one-x-v3.txt` both pass.

`c388-odd-manager-events.jsonl` records actual viewport1235×743, GDK1,
resize-guest:false, and matching monitor/pixbuf dimensions. Root visually reviewed
`c388-odd-desktop.png` as a correctly sized desktop. This is explicit existing-mode
selection, **not automatic odd-size resizing**, a new hiDPI=0 holder, adaptive DPI
inference, or full3840×2160 at1x qualification. Candidate390's fixed lifetime scale
and persistent preference implementation remains native-unqualified here.

## Failed observers and input attempts retained

The initial probe in `c388-odd-mode-result.txt` rejected expected mirror-source
membership before mutation. The next `c388-odd-mode-v2-result.txt` configured the
mode but rejected the existing mirror destination's native mode adaptation.
Their original false results remain evidence. The revised observer preserves exact
preconfigure checks and, after configuration, allows only mode/frame-size changes
of an already existing mirror destination while retaining IDs, origins and mirror
graph. It does not waive unrelated display changes.

The first pointer attempt reached two top targets, then encountered Dock
obstruction over lower targets. `c388-input-odd-timed-result.txt` remains
passed:false, target_hits2, missed1; `c388-odd-input.png` retains the obstruction.
The retest clicks visible portions of the same lower targets and passes all five
hits, zero misses, exact token `RGPUB821A650`, and geometry_changes0 at1235×743,
backing scale1 (`c388-input-visible-result.txt`). This is a separate positive
attempt, not a rewritten first verdict.

An lsof observer queried an absent tty alias. The corrected exact
`tty.com.redhat.spice.0` query identifies agent759/fd5. The observer error is not
interpreted as missing or replaced agent ownership.

## Audio, restoration and lifecycle

`c388-audio-result.txt` passes48kHz stereo sample delivery with approximately
997/1498Hz tones and channel separation. The independent restoration JSON confirms
sink, volume, mute, defaults and owned-module removal. Endpoint audibility and A/V
synchronization remain unqualified.

Closing the owned viewer leaves the exact VM alive. Final3840×2160 HiDPI restoration
passes and the capture identity remains unchanged. Harness shutdown is
exited-after-guest-request; private terminal is guest-shutdown/process_exited:true.
Docker records container die(exit0)/destroy, no container kill/stop. Both capture
hooks report natural-container-exit, deferred0.389715/0.389775s, no shutdown-event
wait and no completed-original-zombie branch. Console ends with EOF and critical
transport with receive reset; these are distinct outcomes.

Critical snapshot18 contains367 records accepted as a terminal prefix, with zero
corrupt or incomplete snapshots. A terminal prefix is still not a complete tail.
Recovery is recovered and authorizes_launch:true. Host remained awake, vfio-pci,
power/control=on. Full host suite1426 tests/eight skipped passed in54.145s before
launch; this does not replace native proof. The companion bounded manifest hashes
actual relevant results, observer failures, screenshots and lifecycle receipts.

Dev's previously delivered candidate386 and its green hosted CI remain separate
from this diagnostic. No candidate390 functionality, universal60Hz, all-manager,
VirtualBox or clean-user setup qualification follows from this run.
