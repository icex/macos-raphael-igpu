# Candidate 186 headless Lilu staging review

## Scope

Candidate 186 / `metal-019` preserves the candidate-185 Raphael source tree at
SHA-256 `db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0`.
Its only runtime change is the audited Lilu 1.6.8 bundle, selected by
`-liluheadless`; `rgpudump=5000` replaces the 40-second diagnostic delay. The
card preserves the no-generic/no-ramfb topology, 180-second exposure, unchanged
45-second probe, recovery helpers, CR2 transport, and candidate-185 functional
boot arguments.

## Readiness audit

The existing run loop treats incomplete transport snapshots as pending before it
calls the readiness classifier. A complete early snapshot was also checked with
the actual `metal-018-185` manifest and correct build record but zero route,
lease, or accelerator-start records. `classify_probe_readiness` returned:

```json
{"earliest_failure":"identity_or_route_missing","valid":false,"verdict":"INCONCLUSIVE"}
```

The loop continues polling on this result. It stops after the settling window
only for a non-`INCONCLUSIVE` result. The shorter dump delay therefore does not
turn legitimate early evidence into an abort or premature decision.

## Artifact and media contract

`tools/stage-candidate.py` requires candidate 186 callers to supply the Lilu
bundle and exact executable, Info.plist, and parent build-manifest hashes. It
checks bundle identity `as.vit9696.Lilu`, version 1.6.8, x86_64
`MH_KEXT_BUNDLE`, unsigned build metadata, and the three supplied pins. The
audited durable inputs are:

- bundle: `/home/bogdan/macos-vm/run/headless-lilu-verified-53b5a19812e6/Lilu.kext`
- executable: `53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887`
- Info.plist: `6714fee51444238c0540814729767485572441435bcf36a158571cf78317a669`
- build manifest: `e5d2554d29658699dd9535a9b8dd38ca9aae5aa5a12f65508b083d3c519cf378`

Staging still mutates only a private raw copy first. The candidate-186 path then
replaces Lilu on that private copy and accepts it only after one combined
Raphael/Lilu/config readback. Both the prepublication candidate qcow2 and the
published qcow2 receive the same five-file readback. `staging.json` is linked
only after final qcow2 verification and records the Lilu path and all three Lilu
hashes. Existing rollback restores the raw image, qcow2, and host config before
removing owned metadata if any final readback fails.

## Focused verification

`python3 -m unittest tests.test_stage_candidate` passed 29 tests. These cover the
new exact metadata and boot contract, version-186 staging defaults, Lilu input
pins, wrong Lilu and config readback preserving the private preimage, readback
ordering before media/metadata publication, and historical card selection.
`python3 -m py_compile tools/stage-candidate.py` also passed. The checked-in
`metal-019` digest is
`a7b9f36bfbb6da0ea1d93675d3ac51c951035da51a7ba64783373857888dee77`.

No candidate build, real stage, VM launch, device access, sudo, publication, or
commit was performed.
