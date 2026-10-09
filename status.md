# Live status — 2026-10-09

## Candidate 394: windowed snapshot desktop works; explicit cleanup fails

Run `af7889e45df129e345d9c7f6b03525cd`, metal-217, version1.0.394,
MODE2 #314, boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Launch59b5ee6, build source de9518d, build ID778fdc6a957a441eac7d0215ccccd33b.
Executable SHA2566d2eb6ec48abef60bf102240f0ba8cc8d048e3ec5814a468c6ddd1a1e9cbda97.

Native private staging isolates retired mappings: both 801×601 host images match
all481401 pixels after old-owner writes, including writes after the new ACK.
Old COMMIT/re-ARM and incompatible cache mappings are refused. Four retained
buffers exhaust the bounded pool as intended. However, the fixture FAILS at
release-A-capacity with cleanup_ok=false. Individual unmap return codes were not
logged. Source inspection identifies retired-owner memory lookup preventing
explicit unmap; candidate395 retains each client's own descriptor through retirement
and adds native remap/unmap result checks. This fix is built, not natively tested.

Installed immutable capture selects the new restart capability without replacing
the sealed capture app or changing TCC consent. A real virt-manager desktop is
visible, with exact1235×743,1237×745 and1441×961 resize responses. Two normal helper
restarts reacquire capture successfully. Default stereo sample delivery passes;
independent audio-route restoration checks all pass. This does not qualify endpoint
audibility, A/V sync, sustained60Hz, all-frame integrity or crash races. The bounded
viewer exits while the identity-matched VM remains alive. No394 pointer test was run.

Shutdown: capture-abort-after-request, both hooks immediate-stop while original
QEMU PID113 remains R with one task. Docker records SIGKILL and exit137; private
terminal receipt is missing. Reporting now correctly distinguishes this forced
shutdown. The underlying capture-exit race remains open. Recovery is recovered,
authorizes_launch=true; GPU stays vfio-pci, power/control=on. Host awake service
remains active. No VM is running. CORE_PROBE_PASS is a narrow functional result.

Evidence: run/candidate-394-results; c394-native-{before,after}-pixels.json;
c394-native-final.txt; c394-snapshot-desktop.png; c394-resize-manager.jsonl;
c394-final-state.txt and decoded logs; c394-audio-result.txt;
c394-audio-restored-independent.json; c394-viewer-close-alive.json;
c394-docker-events.jsonl. Pre-exposure archive-path refusal after MODE2 #313 did
not consume a GPU ledger entry. Full host suite1453 tests,8 skipped passes.

Next: candidate395 must demonstrate explicit retired-buffer unmap, bounded capacity
recovery and installed presenter reuse on hardware. Separately investigate the
capture-exit race without weakening abort or recovery gates. Then measure sustained
presentation and broaden lifecycle qualification. VirtualBox transport remains
unimplemented; QEMU/virt-manager success is not VirtualBox support.

Last delivered dev48b4c96 passes hosted test/build run37983196350 and contains
tested392 kext/bin. Current394/395 changes remain candidate-only. Main unchanged.
