# Live status — 2026-10-09

## Candidate386: persistent window resize, input and reconnect pass

Run `e5d5d205577125364146f54224bbd3f6`, metal213,1.0.386,MODE2#309,
bootba51b3c6. Built source17e907790afba76b50976da674ae75a6a411cc72,
buildded62ba27d244bf892d516099cc7335d. Executable SHA256
781269e526cb3dce4736f5b3f031bdfb1f441ec2abd7f81d0e7ccd8cf7d20457.
Guest boot6A97FB22-D9FD-4639-A869-F257061672A1 reused installed support
4d424e4034ed6cf6a1f44bd6490e52406fa8d9f25cb1e1ac59692a8f7daf3a46.
Holder612, presenter769 and resize agent768 started automatically; ttyfd5 attached.
The sealed capture app/receipt/CDHash remain identical to385, no new TCC prompt.

SPICE agent-mouse=off retains USB-tablet delivery while the resize agent stays
attached. Actual manager GDK1 surfaces1460x960→1440x960 match. The native input
fixture passes five targets/zero misses/exact keyboard token. A deliberate transient
geometry-change control fails with4changes despite restoring the final mode;
one unchanged notification is retained without falsely failing the stable test.
After closing/reopening the viewer,1502x960→1440x960 surfaces match; input passes
again with geometry_changes0 and unchanged holder/presenter/agent. Closing this
viewer leaves the exact VM alive. Final3840x2160 restoration passes.

Default guest stereo sample capture passes48kHz997/1498Hz; independent sink,
volume,mute,defaults and owned-module restoration all pass. This does not prove
physical endpoint audibility or A/V sync. The display stays awake during testing.
Final logs retain two refused count0 monitor requests and one ConnectionRefusedError
request8 during the direct geometry-control test; later requests succeed. A final
capture-identity observer first ran as root and failed ownership checks; rerunning
as the actual user501 passes with the original seal. No capture app was modified.

Shutdown: harness exited-after-guest-request, private terminal guest-shutdown with
process_exited=true. Docker container die0/destroy, no kill/stop. Both capture hooks
natural-container-exit, deferred~0.401s, shutdown_event_wait=false, zombie=false;
console clean-eof, critical recv-reset. Recovery recovered/authorizes_launch=true.
Critical snapshot18 accepted terminal-prefix;1invalid-chunk-bounds line and
incomplete snapshot7(318validchunks,noEND) retained. CORE_PROBE_PASS remains narrow;
the early window probe has zero observed presented frames and does not qualify
performance. Host remains awake, vfio-pci, power/control=on; no reboot/rebind.

Evidence: run/candidate-386-results; c386-persistence.txt;
c386-input-positive-result.txt; c386-input-negative-result.txt;
c386-reconnect-manager-events.jsonl; c386-input-reconnect-result.txt;
c386-audio-result.txt; c386-audio-restored-independent.json;
c386-final-state.txt; c386-final-capture-identity-user.txt;
c386-viewer-close-alive.json; c386-docker-events.jsonl.
Mouse-routing host suite1426tests/8skip passed; staging88tests passed.

Next: deliver the verified385/386 support and tested386 binary with updated docs
and green exact-commit hosted CI. Resize currently accepts even physical
640..3840x480..2160 only and forcesHiDPI2; at GDK1 this halves the logical workspace.
Odd-size/DPI policy, full-frame corruption/performance, forced-stop/crash and other
VM managers/VirtualBox remain open. Delivered dev remainsc6d7ef1 with hosted
37968448791 test/build green until the new delivery passes. Main unchanged.
