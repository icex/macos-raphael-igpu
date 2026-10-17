# Candidate203 nq2 classifier audit

The immutable first-decision receipt for nq2 records `SUB: routes=ok count=7 entries-match=1 capture=armed` (build `1075be638c024db79cf6ba022a73e631`, serial prefix SHA-256 `175accfb503f8b512148e23be4198a00f413b55ee71e52fc6211f6beff5f945c`, critical prefix SHA-256 `99422a9a549b300ba1610c9bc4cd26b9a793cce4163a9dc96e997322046a0e4a`). Current source registers seven submission routes after the reviewed `wireSysMemory` removal. The classifier accepted only five or six, and its backing route guard required six, so it rejected the first decision at `submission_trace_route_guard` before any workload decision.

The current source also emits backing samples with the fields `pool=<n>` and `counters=<...>-><...>`. The parser's older format rejected these as malformed, causing the next false refusal at `submission_backing_allocation_observation_malformed` after the route count was corrected.

The candidate203 worktree classifier now accepts route counts 5/6/7 for legacy/current source compatibility, accepts the optional current backing fields, and permits 6/7 in the backing route guard. No guard was removed and no result was inferred from workload records.

Full replay used an isolated `/tmp/candidate203-nq2-full-replay` copy of the original manifest plus `first-decision-serial.txt` and `first-decision-critical.txt`; original files and `verdict.json` were untouched. Replay result after the bounded fixes is `valid=true`, `verdict=PROBE_NOT_RUN`, with no earliest failure. This means the first-decision refusal is repaired; it does not claim the later capture-loss result or a Metal probe outcome is repaired.

Validation from candidate203 worktree:

`python3 -m unittest -q tests.test_classify_run tests.test_functional_regression` — 91 passed.

The separate later capture-loss verdict remains evidence about capture completeness and is not conflated with this classifier contract correction.
