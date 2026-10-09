# Candidate 356: native recv-reset completion and manager input

Run `684122f412ad335d91c07cdfece852dd`, metal-199, MODE2#295,
run commit `97940f369d324503b69b920e9ab3bf2c62313f97`, build
`3f0b17ede8914d26b68a55bb3a56042e`. Full-refresh image/property and signed O2
presenter unchanged. [Hashed artifacts](libvirt-reset-native-evidence-20261009.json).

## Native shutdown result

The genuine bound SHUTDOWN_GUEST event was observed at monotonic65481.181851653.
Critical recv-reset104 at65481.183253967 followed1.402ms later; console cleanEOF
at65481.183277487 followed1.426ms later. They retain distinct records. The critical
collector error is not relabeled cleanEOF. Both capture hooks found completed
process state and observed natural container exit in0.373s. Their
`shutdown_event_wait=false`: the new pending-worker wait remains native-unexercised.
The independent50ms watcher saw original leader113Z plus CPU0/KVM119R at
65481.231751261, then process absent at65481.332243778. This observation does not
claim the hooks themselves saw that transient state.

Real terminal has `reason=guest-shutdown`, `process_exited=true`, exact run/CID/start
identity. Critical final bytes2440973 and SHA86123781426612e5db3cc2b8b00e536f967e1dad7e34ba7deba5b20ba5b49b1a
match the fresh quiesce ACK (snapshot18,365records). CORE_PROBE_PASS,
earliest_failure=null; recovery recovered/authorizes_launch=true. No reboot/rebind.
This is positive native correction of355's missing reset observation/completion
handling, not universal crash recovery or proof of all deferred-wait branches.

## Actual virt-manager input

On the real KWin/Wayland desktop, virt-manager5.1 PID872949 showed the admitted
HiDPI desktop. Computer Use screenshots and compositor window enumeration supplied
host coordinates; click input traversed host uinput, GTK/SPICE and guest USB tablet.
The tool keyboard backend could not find ydotool. A bounded evdev UInput keyboard
instead sent actual host key events to the focused viewer; no clipboard or direct
SPICE/QMP input was used. Exact guest nonces establish delivered keys.

| Host viewport | Five targets | Exact token | Misses | Guest mode changes |
|---|---|---|---|---|
| normal1288x909 | pass | pass |0|0|
| small1000x760 | reached | pass |2|0|
| fullscreen1920x1080 | pass | pass |0|0|

All retain1920x1080 logical/backing_scale2. Small-window resizing used an actual
host bottom-right drag; compositor confirmed1000x760. The first two automated
clicks at its visible top-left target instead arrived at the prior guest center
959.414,538.978. After leaving/reentering canvas and a bounded relative-mouse
movement/click, every target was reachable. Preserve the failed small result;
root cause could be automation motion/enter sequencing or viewer state, and is
not established. Normal/fullscreen success does not qualify arbitrary resize.
Top-right targets were partly covered by a Tips banner; clicks used the visible
cyan lower edge within the fixture's target bounds.

The viewer service was closed independently; exact CID/start remained alive.
Reopening as PID881751 restored a visible1288x909 desktop. Final awake assertions
were retained. Shutdown then used only stop-requested through the harness.

## Next

Discriminate host pointer motion/enter after resize; qualify repeated transitions.
Console USB audio is being prepared separately. Installation durability, broader
desktop workloads and VirtualBox remain open.1224 host tests/8skip and stage87
passed before exposure; no executable code changed during this run.
