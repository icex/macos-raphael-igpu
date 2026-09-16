# Historical Metal execution audit: candidates 190–194

Date: 2026-09-13. This is a read-only evidence audit. “Passed” below means
the probe’s own checked results; it does not override the harness verdict or
prove desktop presentation.

## Strongest positive evidence

The strongest artifact is the resealed candidate-194 run:
`/home/bogdan/macos-vm/run/metal-028-194-resealed/probe.json`. Its manifest
binds run `1f0649a6a31fbf73162696891cf5b9bc`, build
`3e18ed7889554b9295ca5195406489fb`, boot
`f828eb26-9cb7-4fac-bff2-bc87515fa2ba`, binary SHA-256
`7623059a5ea035f929f9e10d6aad35cda698d643bbe2a2801a649eeed19fd24e`, source
commit `52c751707c42ad037669872c081eb66bc4e2fd04`, and `source_clean=true`.
The probe reports device `AMD Radeon Navi23`, `metal3=true`, three compute
rounds with `compute_values_checked=196608`, four completed command buffers,
and `render_pixels_checked=4096`; it exits 0 with `passed=true`.

This is direct evidence that the Metal workload executed far enough to produce
the requested compute and offscreen render/readback checks during that VM run.
It is not a fully qualified experiment result: the same run’s
`verdict.json` is `INCONCLUSIVE`, with `earliest_failure=identity_or_route_missing`
and `evidence=[capture_loss]`. Therefore the defensible classification is
**hardware functional result: true; authenticated/qualified run verdict:
uncertain**. The probe’s run ID, output, and transport exit agree, but the
missing required capture prevents the project’s evidence policy from promoting
it to a clean pass.

## Candidates 190–193 and the unre-sealed 194 run

| Artifact | Bound result | Classification |
|---|---|---|
| `metal-024-190` | `verdict=INVALID`, critical capture incomplete; no `probe.json` | No Metal execution evidence |
| `metal-025-191` | run `20187457d3e5ad837617f89efa477219`, device enumerated, Metal 3; compute command buffer timeout, completed buffers 0, values 0 | **False** for functional completion |
| `metal-026-192` | run `575d67d557b07f98b186c0cfb024fcbd`, device enumerated, Metal 3; same five-second timeout, completed buffers 0, values 0 | **False** for functional completion |
| `metal-027-193` | `verdict=INCONCLUSIVE`, capture loss; no `probe.json` | Uncertain/unobserved |
| `metal-028-194` | `verdict=INCONCLUSIVE`/no probe artifact | Uncertain/unobserved |
| `metal-028-194-resealed` | direct positive probe above; harness verdict inconclusive | True workload result, uncertain qualification |

Enumeration and `metal3=true` in 191/192 establish device discovery only.
Their zero completion and zero checked values establish failed functional
completion for those two probes. They do not contradict the later 194 result
because the binaries, source commits, and run conditions differ.

## Earlier claim corroboration

The earlier hybrid cycle 014 artifact is
`/home/bogdan/macos-vm/run/metal-030-194d-output`, build
`3e18ed7889554b9295ca5195406489fb`, run
`9a4c2e7b1d5f3086a2c4e6f8b0d1a3c5`, boot
`2ac68c8a-c6f5-4b0e-a7b7-1fde8390680a`. Its checksum-valid CR2/serial audit
records KIQ stamps 1–3 returning 1, then stamps 4–9 returning 0, alongside
`backing-summary completed=7268 true=233 false=7035`. This supports the older
claim that real WindowServer Metal submissions reached KIQ completion before a
later retirement failure. It does not establish a complete probe pass,
drawable presentation, or sustained desktop acceleration.

The status wording “candidate 194 proved real Metal compute and offscreen
render/readback” is supported by the resealed probe’s checked counts, provided
it is read as a raw functional observation. The same status correctly retains
the qualification limits: the run verdict was inconclusive and desktop,
repeatable recovery, and physical display remain unproven.
