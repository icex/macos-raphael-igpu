Experimental RaphaelGPU 1.0.164 diagnostic snapshot for Sequoia 15.7.9 (24G830).

- Hardware-tested163 reproduced real KIQ completion and located the next failure:
  SDMA hybrid types10/11 succeed, then type10 fails with native status4.
- Candidate164 observes the actual native SDMA instance lookup, including requested
  index, returned instance and queue capacities. It preserves native arguments/results
  and adds no GPU register writes. This new hook is not hardware-validated.
- Adds immutable build/ESP/QEMU identities, concurrent critical diagnostic records,
  explicit missing-data classification and one bounded experiment per host boot.
- Full Metal remains unavailable. No compute/render command completion and no
  playable game have been verified. Native shutdown/reuse remains unqualified.
- Tests and hosted source builds do not establish physical GPU or host stability.

Three historical host hard hangs remain unexplained. This is a research prerelease,
not a stable or game-ready driver. See docs/ROADMAP.md and the archived experiments.
