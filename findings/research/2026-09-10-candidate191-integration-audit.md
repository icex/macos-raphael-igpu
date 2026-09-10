# Candidate 191 offline integration audit

Date: 2026-09-10. No build, staging, VM, VFIO, reset, recovery, or hardware
operation was performed.

The final `metal-025` contract retains the known-boot dynamic `GDB=on`, headless
custom-media launch settings, candidate 190's Raphael source digest, 180-second
exposure, strict unchanged 45-second native Metal probe, cleanup, capture-loss,
and no-automatic-retry gates. It changes only the live serial-path exact-CID
binding and UART producer/collector deadline handling. Neither the card nor the
staging implementation requests `slide=0`, `GDB=wait`, or early rendezvous.
The four GDB observations are conditional diagnostics available only after an
actual probe failure; none can delay or replace the primary Metal probe.

The unqualified early-rendezvous proposal is preserved only as blocked research.
Its historical `slide=0`/OpenCore evidence is not part of candidate 191 and does
not impose an early-GDB acceptance requirement on the next experiment.

Fresh final verification on the stable tree:

- Python discovery: 718 tests passed, 3 skipped.
- All 17 C++ fixtures compiled with C++17, pthread, ASan, UBSan,
  `-Wall -Wextra -Werror`, and all executed successfully.
- Python compilation, `Info.plist` validation, and `git diff --check` passed.

Reviewed SHA-256 values:

```text
3738e6d59fb0f95adcc3690676047f6af8257db708dada546ac2641ae50074eb  experiments/metal-025.json
f0e470b2f1705230529bb109907323961efd8c44bf53dfb3c823061efe9b4f3d  tools/stage-candidate.py
e9d910418322b8a7f64baa2984dd8ae76d474b3fbb3142e61843efba717d8273  kext/Info.plist
89b24bcb712f229894e0f4bde6938eba9f64b92a2e69559b86a93993f5ad422a  tools/run-bounded-gdb.py
3dd229f4ea4df1c0d3a9f3c5f50becd69b2664bf85ebe8c515893488ceaa4ad8  tools/sercat.py
8b3f148b1f0393fdda2f255bff15f99c808f8a8d7d46af9e141362f43803cae0  tools/experiment.py
1cf09317a8cf32c4055b3d2f6b515c1233a0fb45f67d4fdb81257df5060cb477  tools/recover-incomplete-cr2.py
```

The offline integration review found no remaining blocker to committing this
milestone. It does not establish a successful candidate build, boot, debugger
rendezvous, GPU execution, Metal result, or repeatable future cleanup.
