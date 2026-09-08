Experimental RaphaelGPU 1.0.164 diagnostic snapshot for Sequoia 15.7.9 (24G830).

- Hardware-tested163 reproduced real KIQ completion and located the next failure:
  SDMA hybrid types10/11 succeed, then type10 fails with native status4.
- Hardware-tested164 proves the failed request is SDMA type0/global-index1: TTL reports
  one discovered instance, so the native lookup returns null before its callback. X6000
  unconditionally constructs two Navi23 SDMA objects.
- Candidate164 completed an orderly root-agent shutdown with APFS unmount and CPU halt.
  Full GPU teardown and warm reuse are not yet established.
- Adds immutable build/ESP/QEMU identities, concurrent critical diagnostic records,
  explicit missing-data classification and one bounded experiment per host boot.
- Full Metal remains unavailable. No compute/render command completion and no
  playable game have been verified. Native shutdown/reuse remains unqualified.
- Tests and hosted source builds do not establish physical GPU or host stability.

Three historical host hard hangs remain unexplained. This is a research prerelease,
not a stable or game-ready driver. See docs/ROADMAP.md and the archived experiments.
