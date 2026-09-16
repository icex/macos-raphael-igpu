# Live status — 2026-09-16

**Candidate280 passes the bounded visual, codec and cleanup checks.** The reproduced
Screen Sharing transparency defect is fixed; routine critical-log exhaustion is
also corrected. Full desktop and physical display qualification remain open.

## Current host / guest

Guest is **stopped** after run4eeb58b45c54db193ec9b14421f23f33,
candidate280/cardmetal-127, MODE2#156, sixteenth exposure on host boot
2508eb6d-ddf3-497d-9774-00a7ecebe3ed. GPU0000:7b:00.0 remains vfio-pci,
power/control=on. Results: `/home/bogdan/macos-vm/run/candidate-280-results`.

Functional checks passed; identity/capture valid,398critical records with no loss.
Shutdown: exited-after-guest-request. Recovery: schema6/recovered,
authorizes_launch=true, CP_STAT=0, active_after=0, no forced HQD clears.
Overall **CORE_PROBE_PASS**, which does not qualify the entire desktop roadmap.

## Verified current changes

- **Transparency:** exact UUID/byte-guarded feedback expansion repair retained.
  Fresh280 unobstructed raw RFB captures show clean animated native panels.
  Four independently seeded processes (two sequential, two concurrent) pass
  48cases/5,280,000pixels with no mismatches, maximum error1byte. Fresh279 passed
  the original12cases and the user reported no more corruption.
- **Capture:** routine image queries/packet dumps remain in ordinary serial;
  successful COW critical records are bounded, failures remain critical. Strict
  loss detection and recovery checks are unchanged. Final398/512records,0drops.
- **Codecs:** fresh120-frame HEVC and120-frame H.264 hardware encode/decode pass,
  maxlumaerror0/1. Original seven sustained cases/9,600frames remain separate
  evidence. Explicit decoder GPU-ID selection remains unsupported; automatic
  required-hardware selection works. Main10/chroma/arbitrary-media/concurrency
  remain unqualified.
- **PerfPowerServices:** corrected QEMU now observed on three fresh guest boots
  on this host boot; latest0.0% CPU/0.77s cumulative after graphics/codecs.
- **Host suite:**938tests OK,3skipped.

Driver build51bfd732cf824249b70981f0c36fe314; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Visual mechanism](findings/research/feedback-decompression-20260916.md),
[capture correction and scope](findings/research/critical-record-overflow-20260916.md),
[280 artifact hashes](findings/research/candidate-280-qualification-20260916.json).

## Remaining work

1. Measure M5 resource reclamation across bounded allocation/recreation cycles;
   current distinct-seed concurrency evidence covers BGRA8 feedback only.
2. Longer ordinary desktop interaction, broader synchronization/format coverage,
   M7 independent-host-boot and crash/closure qualification.
3. Physical DCN output and performance qualification after correctness gates.

Historical candidate278 direct OpenGL hang and live-validation crash remain
unresolved. No main merge/push before full desktop proof. Additional exposure
requires a named-boot allowance and fresh successful MODE2 through tools/cycle.py.
No vfio→amdgpu cycling. [Roadmap](docs/ROADMAP.md).

## Next bounded run allowance

Standing user instructions authorize the seventeenth exposure on host boot
2508eb6d-ddf3-497d-9774-00a7ecebe3ed, same280/cardmetal-127, attempt reclamation.
Purpose:32measured allocation/copy/release rounds after3warmups,48MiB live resources,
CPU-check every output and sample process-local Metal allocation return, followed
by clean shutdown/recovery. Prior280 has an authorizing recovery receipt. Fresh
MODE2 must show CP_STAT=0/RLC_CNTL=0; all identity, capture, host-fault and cleanup
aborts retained. Maximum6000seconds; stop manually after the bounded checks.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-280-attempt-reclamation-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
