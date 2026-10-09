# Live status — 2026-10-09

## Candidate388: odd 1x modes work on the existing virtual display

Run `f61db53ed51c02394163eb0ba7e08367`, metal214,1.0.388,MODE2#310,
bootba51b3c6. Sourcecaab7d8, build95053dc30d5e479cbeec0ec58a119168;
executablea82d6cd0d017c2f62d3614c5f4a6e6cc7cc6ca59c9d5248e6ffe0daf0c9cfcff.
Installed support4d424e40 starts holder617,resize agent759,presenter760; capture
app/receipt/CDHash unchanged, ordinary presenter (snapshot unarmed), awake.

Existing holder control adds2470x1486 physical/1235x743 logical. Native enumeration
shows both that2x mode and1235x743 physical/logical1x. Diagnostic source389ef586a2
selects both directions on the same holder/presenter with exact settled readback.
Actual manager viewport1235x743,GDK1,resize-guest=false has matching SPICE monitor
and pixbuf sizes; screenshot shows a correctly sized desktop. This is explicit
selection evidence, not yet automatic resize at1x or a new hiDPI=0 holder.

Retained observer failures: original probe rejected expected mirror-source
membership before mutation. Next probe configured successfully but rejected the
mirror destination's native mode adaptation. Revised observer keeps exact
preconfigure checks and permits only mode/frame-size adaptation of an existing
mirror destination after configuration, preserving identities/origins/mirror graph.
Original results remain false. Initial pointer attempt hits two top targets then
fails because Dock covers lower targets (screenshot records obstruction). Retest
clicks visible portions of the same lower targets: five hits, zero misses, exact
RGPUB821A650 token, geometry_changes0, passed=true, same1235x743/backing_scale1.
An lsof observer queried an absent tty alias; exact tty.com.redhat.spice.0 shows
agent759/fd5. These observer errors are not hidden or counted as passes.

Default stereo sample capture48kHz997/1498Hz passes; independent route/volume/
mute/defaults/module restoration all pass. Endpoint audibility/A-V sync unqualified.
Closing owned viewer leaves exact VM alive; final3840x2160 HiDPI restoration passes.
Shutdown exited-after-guest-request; private terminal guest-shutdown/process_exited
true; Docker die0/destroy, no container kill/stop. Both capture hooks natural exit,
deferred~0.390s, no shutdown-event wait/zombie; consoleEOF,criticalRST. Critical
snapshot18(367records) terminal-prefix accepted, zero corrupt/incomplete snapshots.
Recovery recovered/authorizes_launch=true. Host awake,vfio-pci,power/control=on.

Evidence: run/candidate-388-results; c388-scale-setup.txt;
c388-odd-mode-result.txt;c388-odd-mode-v2-result.txt;c388-restore-two-x-v3.txt;
c388-one-x-v3.txt;c388-odd-manager-events.jsonl;c388-odd-desktop.png;
c388-input-odd-timed-result.txt;c388-odd-input.png;c388-input-visible-result.txt;
c388-audio-result.txt;c388-audio-restored-independent.json;
c388-final-state.txt;c388-final-capture-identity.txt;c388-docker-events.jsonl.
Full host suite1426tests/8skip54.145s passes; native scale/input probes compile.

Delivered devc8fc5d5296d33e15c6f1284dd9c43024ae62eecd includes tested386 kext/bin,
resize/input/lifecycle docs; hosted37975249900 test/build success, release skipped.
Main unchanged. Candidate390 prepares explicit persistent1x/2x scale and v2 control
requests; fixed hiDPI=0,odd automatic resizing,full4K1x and persisted choice need
native qualification. Full-frame integrity/performance,forced-stop/crash,other
managers/VirtualBox and broader roadmap remain open. No new388binary delivery yet.
