# Candidate390: explicit scale and public-mode ordering (partial run)

Run `3d0e4869c7f1c49af50497f440996a5b`, build
`c1591507f28f48e7a42b8ce3e92f6c51`, executable SHA256
`7bbd044587498bae26e1daf182a36c9d2147ddfb59c99e9108dd80128d48dad9`.
This report covers stable functional artifacts only. The completed cadence window is recorded below;
shutdown/recovery completed as recorded below. Root owns all native operations.

## Initial failure and source-grounded correction

Native compile/ABI and addon installation passed with the sealed capture app
unchanged. The initial scale1 holder908/presenter963/agent962 handled odd1235×743
through v2 control, but initial4K selection failed and fell back to2048×1536.
`c390-first-four-k.txt` retains a3840×2160 request accepted into the mode table
but ending status4 because public enumeration lacked that exact mode.

`c390-raw-modes.txt` proves valid raw1x modes13/18/20 exist (flags3), while public
CG enumeration omits them. Generated equivalent2x descriptors36/37/40 lack the
validity bit yet trigger SkyLight's larger-than-native1x suppression. The first
advertised2048×1536 mode carried the native flag; larger3840×2304 was visible,
contradicting a simple maximum-size explanation.

Candidate391 `4826f69` moves the existing3840×2304 default first only for scale1,
retaining all modes, bounds and scale2 ordering. Native v2 installation then
reports initial_selected:true at3840×2160 physical/logical; an ordinary public
control request returns exact4K status0 (`c390-v2-four-k.txt`). No private mode
configuration, cache purge, serial change, or binary patch was executed. The
unused private mutating diagnostic was removed; read-only raw inventory remains.

## Protocol, automatic odd resize and input

`c390-native-framing-results.txt` retains malformed framing rejection(status1),
no-EOF bounded closure, fragmented successful request, and lifetime-scale mismatch
refusal(status2), with independent mode snapshots around the controls. Its scope
is the exercised framing cases, not arbitrary hostile-stream qualification.

`c390-v2-auto-manager-events.jsonl` records four exact settled surfaces:
1235×743,1237×745,1441×961,1235×743. `c390-input-v2-final.txt` passes five hits,
zero misses and zero geometry changes. This qualifies tested automatic odd-size
requests and input with the scale1 holder; it does not qualify every manager.

`c390-v2-audio-result.txt` passes isolated stereo sample delivery, and
`c390-v2-audio-restored-independent.json` confirms sink, volume, mute, defaults
and owned-module removal. Endpoint audibility and A/V synchronization remain open.
Capture application/receipt/signature identities remain unchanged through support
updates, distinct from holder/agent restarts required to change lifetime scale.

## Scale2 compatibility and return to scale1

`c390-scale2-check.txt` records the explicit owned restart at scale2, original
mode order, and successful legacy-v1 request2000×1000 physical→1000×500 logical.
Odd scale2 geometry is refused by the client; a mismatched scale1-v2 request is
refused status2 without changing2000×1000. These are retained negative controls,
not unexpected failures. `c390-matched1x-prep.txt` records restored scale1 with
initial4K selected, then exact1440×900 physical/logical preparation.

The policy is explicit1x/2x per holder, not inferred from advisory SPICE mm or
host GDK scale. Preference changes take effect at the next owned restart.
Measured cadence and final cleanup is recorded below;
no universal60Hz, full-frame integrity, new guest-boot preference persistence,
first-user setup, or VirtualBox qualification is claimed here.

## Matched scale1 mixed-workload observation

The ordinary presenter remained active and snapshot ownership **unarmed**. Final
support payload is `5ed647ae17f902d25daf30021a29b50e64e2f27660dc85d8d84c668dd3697633`,
holder2970, agent3023, presenter3024. `c390-matched-1x-analysis.json` associates
actual manager token samples with source DRAW IDs at1440×900 physical/logical
matched to the GDK1 viewport. Over100.006 seconds it records5795 distinct IDs, one
duplicate,13 startup-invalid samples and zero post-start invalid samples. The
first five alternating localized/full-field phases each observe about57.9–58.0
distinct ID intervals/s. The source finishes6600 draw calls over110 seconds; the
last source phase is outside this100-second observer window and is not qualified.

This is sampled token delivery, not universal60Hz, GPU frame rate, scanout, complete
frame integrity or end-to-end latency. There is no source CRC window or snapshot
counter qualification in this case. Guest and manager clocks are not subtracted.
Root viewed the restored ordinary desktop in `c390-post-workload-desktop.png`.
Final state, decoded logs and seal checks are retained separately; final shutdown
receipts are recorded below.

## Completed lifecycle and retained allocation errors

Harness shutdown is exited-after-guest-request; recovery is recovered with
authorizes_launch:true. Private libvirt terminal records guest-shutdown and
process_exited:true. Docker events contain container die(exit0)/destroy only,
without container kill/stop. Both capture hooks report natural-container-exit
after about0.4326s, no shutdown-event wait; critical transport is receive reset
and console is clean EOF.

Replay accepts snapshot18 with367 records as a terminal prefix, retaining one
corrupt line14464 and incomplete snapshot14 (896 chunks, no END). This run does
not have the zero-corrupt/incomplete capture result of candidate388.

The retained serial log also contains eight AMD `Failed to allocate` messages
for size60293120 near lines3646–3653, reporting about77–81MB free and fixed-free
1883172864. Their relationship to tested resize, mode ordering, or cadence is not
established. Successful functional probes do not make the run error-free; root
will investigate this separately after preference persistence qualification.
