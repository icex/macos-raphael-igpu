Experimental RaphaelGPU 1.0.165 candidate for Sequoia 15.7.9 (24G830).

- Hardware-tested163 reproduced real KIQ completion and located the next failure:
  SDMA hybrid types10/11 succeed, then type10 fails with native status4.
- Hardware-tested164 proves the failed request is SDMA type0/global-index1: TTL reports
  one discovered instance, so the native lookup returns null before its callback. X6000
  unconditionally constructs two Navi23 SDMA objects.
- Candidate165 adds the gated `rgpusdma=1` compatibility boundary: it releases the false
  second object before initialization, starts the surviving native SDMA0 object, preserves
  its Boolean result and native progress bit. Hardware objects outside the Raphael target
  remain on Apple's native path.
- The repair requires the exact `rgpu,raphael-target = RGPU-RAPHAEL\x01` OSData marker on
  the same OpenCore device path as the grafted `ATY,bin_image`. `ocprop.py` adds and removes
  both together, and experiment admission verifies the marker. A real Navi23 using its
  native configuration therefore stays on Apple's unmodified two-instance path.
- All five X6000 entries and routes must validate before the repair can apply. The
  host-tested topology helper rejects invalid counts and preserves valid two-instance input;
  first-engine failures remain failures. No TTL status or GPU completion is forged.
- Preparation and launch-time identity checks require the experiment card's exact
  `rgpusdma=1` argument and the per-device marker. The classifier also requires the exact
  correlated SDMA0/queue-0 then SDMA0/queue-1 event sequence before a probe can run.
- Candidate164 completed an orderly root-agent shutdown with APFS unmount and CPU halt.
  Full GPU teardown and warm reuse are not yet established.
- Adds immutable build/ESP/QEMU identities, concurrent critical diagnostic records,
  explicit missing-data classification and one bounded experiment per host boot.
- Candidate165 is hardware-untested. Full Metal remains unavailable. No compute/render
  command completion and no playable game have been verified. Native shutdown/reuse
  remains unqualified.
- Tests and hosted source builds do not establish physical GPU or host stability.

Three historical host hard hangs remain unexplained. This is a research prerelease,
not a stable or game-ready driver. See docs/ROADMAP.md and the archived experiments.
