# Live status — 2026-10-09

## Candidate 395: restartable private staging qualified within measured scope

Run `074a0b4c757c6c21ae093b604a98763d`, metal-218, version1.0.395,
MODE2 #315, boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Launch87242de, build source0736b77, build ID3e40b3c359bc4250870e118a5fdb7e9d.
Executable SHA2566a4b164ecabd1165ceac95707c87d858f421c70d6cc0d935b6838ecb7e495e62.

The native fixture now passes explicit retired-owner unmap/remap, four-retained
buffer capacity refusal, release/reallocation with zeroed storage, and every
cleanup return. Old-owner COMMIT/re-ARM and incompatible cache aliases remain
refused. Both host801×601 images match all481401 pixels after stale writes,
including after the new owner's ACK. This fixes394's explicit-unmap failure.

Installed snapshot capture starts at4K, returns after fixture ownership release,
and restarts normally with the capture app/seal/consent unchanged. Actual manager
odd1235×743→1237×745 resizing works. Corrected fullscreen input fixture passes
five targets, exact RGPU395C1234 text and unchanged geometry; retain the earlier
wrong-Y and Dock-obstructed attempts as test limitations. The test window now
covers overlays without altering user Dock preferences. Default stereo sample
delivery and independent host audio restoration pass. Endpoint audibility/A-Vsync
remain unqualified. Viewer closure leaves the identity-matched guest alive.

Motion:100s sampled token windows show57.92 distinct IDs/s at1440×900,40.40 overall
at4K, no post-start token errors. At4K localized phases observe about50/s and
full-field phases26/s. Source draw records and presenter timings are retained;
commit averages roughly9–13ms and worker14–20ms in motion windows. These are not
GPU FPS, full-frame motion integrity, scanout or absolute latency.4K60 remains open.

Shutdown completes with a bound private guest-shutdown terminal and Docker die0,
no kill events. Both capture hooks report container-stopped-during-shutdown-wait,
deferred=true. Original shutdown.json conservatively says exit-unverified-after-
request because the classifier only recognizes natural-container-exit for retained
private completion. Independent running/terminal/supervision/plan binding passes;
original receipts remain unchanged. A reporting-only correction is prepared next.
Recovery is recovered/authorizes_launch=true. CORE_PROBE_PASS remains scoped.
Critical replay retains374 records with one invalid-chunk line and incomplete
snapshot7; zero captured panic markers does not mean error-free qualification.

Evidence: run/candidate-395-results; c395-native-{before,after}-pixels.json;
c395-native-final.txt; c395-{matched-1x,fourk}-analysis.json and cadence/source logs;
c395-post-motion-desktop.png; c395-overlay-final.txt; c395-overlay-before.png;
c395-audio-result.txt; c395-audio-restored-independent.json; c395-final-state.txt;
c395-viewer-close-alive.json;
c395-docker-events.jsonl; c395-private-terminal-independent.json.
Full final host suite1453 tests,8 skipped,OK50.932s. Exact tested395 kext/bin copied.
Current docs/report updated; dev delivery and hosted CI verification pending.

Next:396 bounded exit-refusal diagnostics (no admission changes), then397 split
commit timings to locate4K cost. Preserve remaining crash-during-commit, independent
host-boot, first-user setup and whole-frame-motion qualification. VirtualBox7.2.18
contains a VFIO backend, but actual Raphael assignment/console integration remains
unqualified; a source-pinned software-only configuration discriminator is prepared.
No VM is running. Host awake blocker remains active; GPU staysvfio-pci,
power/control=on. Main unchanged; development milestone delivery goes todev.
