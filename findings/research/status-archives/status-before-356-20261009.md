# Live status — 2026-10-09

## Candidate355: desktop passes; critical socket reset prevents terminal receipt

Run `a2e32b7d73a2dc3062421e39b457025c`, metal-198, build1.0.355,
MODE2#294, bootba51b3c6. Native Metal/WindowServer/display pass; normal awake
HiDPI desktop visible in virt-manager. Viewer closure leaves exact VM alive.
Future356 viewport fixture compiles, not yet executed.

Capture CORE_PROBE_PASS, earliest_failure=null. Critical bytes exactly match
quiesce ACK, then guest shutdown is observed; console EOF follows1.454ms later.
Critical collector ends with ConnectionResetError104 and no clean EOF marker.
Its hook force-stops the container; the console hook's exec races that stop.
Terminal absent; outer exited-after-guest-request is not clean completion.
New shutdown-event wait is not exercised. GPU recovery recovered/authorizes_launch=true.
VM/cycle stopped; host awake. No reboot/rebind needed.

Next investigate unread reverse-token socket reset and preserve the old positive
completed-process proof on error-end without mislabeling RST as clean EOF. Keep
live capture loss fatal and the absolute wait/deadline bounds intact.356 viewport
fixture is prepared separately; no next native launch until a reviewed correction.

1214 host tests pass,8skip. Checked-in kext remains353 with matching manifest;
355 build is separately pinned. HiDPI milestone is on dev; CI-only357 fix handles
slow software UART completion and retains failure artifacts. Devdefc0f4 hosted
test/build37930517553 both pass; retained positive ACK took8.652s versus old8s limit.
Main unchanged. General desktop, resize/input, console audio/install durability
and VirtualBox remain open.
[Evidence](findings/research/libvirt-clean-eof-native-20261009.md) ·
[Receipts](findings/research/libvirt-clean-eof-native-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-355-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-356-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
