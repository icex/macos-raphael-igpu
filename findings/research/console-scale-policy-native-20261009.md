# Candidate390: explicit scale and public-mode ordering (partial run)

Run `3d0e4869c7f1c49af50497f440996a5b`, build
`c1591507f28f48e7a42b8ce3e92f6c51`, executable SHA256
`7bbd044587498bae26e1daf182a36c9d2147ddfb59c99e9108dd80128d48dad9`.
This report covers stable functional artifacts only. Cadence measurements and
shutdown/recovery are still pending. Root owns all native operations.

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
Measured cadence and final cleanup must be added separately after completion;
no universal60Hz, full-frame integrity, new guest-boot preference persistence,
first-user setup, or VirtualBox qualification is claimed here.
