# Live status — 2026-10-09

## Candidate396: fresh snapshot desktop and clean supervised completion

Run `3048b197864060d823c97e47ecd64438`, metal219, version1.0.396,
MODE2 #316, host boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Launch0932ba8, build sourceba39a0f, build IDea436cef094b48a7bda10a964918b5a9.
Executable SHA2567bb2002bb3e59277f09504af4d34f74a35c6022683681f627e864e718b696e0c.
Driver source matches395; this run exercises lifecycle diagnostics/reporting.

Installed sealed presenter autostarts snapshot1 at4K with advancing ACKs, then
actual virt-manager resizes to1440×900 and shows the macOS desktop. Display-awake
assertions hold. Viewer closure leaves the same VM alive. This short run does not
repeat395 input/audio/motion or establish a new performance result.

Shutdown is exited-after-guest-request with private_terminal_verified=true. Both
capture hooks report natural-container-exit, Docker dies0 without kill events, and
recovery is recovered/authorizes_launch=true. Critical replay retains365 records
with no corrupt lines or incomplete snapshots. CORE_PROBE_PASS remains scoped.
The R/PF_EXITING refusal did not occur: new bounded fd/task diagnostics were not
exercised, and the earlier capture-exit race is not declared fixed. Reporting now
also recognizes395's bound deferred-wait/private-terminal completion; offline
replay preserves392's forced-abort classification and original artifact hashes.

Evidence: run/candidate-396-results; c396-state.txt; c396-post-resize.txt;
c396-manager-events.jsonl; c396-desktop.png; c396-viewer-close-alive.json;
c396-docker-events.jsonl; c396-shutdown-reconciliation-replay.json.
Full integrated host suite1457 tests,8 skipped,OK50.999s. No VM remains running.
Host awake blocker active; GPU remainsvfio-pci withpower/control=on.

Last delivered milestone: devc1f64d055fb1161f55281972912d0cf4c4178f2f,
hosted test/build PASS run37988921669, release skipped, exact tested395kext/bin.
395 qualifies private staging isolation, explicit retired unmap/capacity recovery,
installed restart, odd resizing, corrected input fixture and stereo sample delivery.
Measured1440×900 tokens~58/s;4K localized~50/s,full-field~26/s, no post-start token
errors. Whole-frame motion,4K60, endpoint audibility/A-Vsync, crash races and
first-user setup remain open.396 changes are candidate-only; main unchanged.

VirtualBox7.2.18 guarded diskless configuration reaches its real pci-vfio backend
and fails at the deliberately impossible path (errno20), then is confirmed powered
off and unregistered. Setuid hardening refused the traced attempt; no successful
syscall trace or actual GPU/DMA/reset/acceleration qualification is claimed.
Pinned source audit identifies unresolved DMA/reset/identity/ROM requirements;
VBoxVGA requires its own presentation adapter. Evidence: run/c396-vbox-dispatch.

Next:397 opt-in bounded stage timings distinguish private-RAM→WC copy/fence,
geometry MMIO, doorbell/host work and ACK checks. Preserve all existing gates and
sealed capture app. Source and build are prepared; native timing qualification
remains outstanding. Continue VBox software boot/presentation investigation
separately, with no physical passthrough inferred from configuration dispatch.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-397-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
