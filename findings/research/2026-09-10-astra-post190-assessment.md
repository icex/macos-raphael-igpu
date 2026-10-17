# Coordinator implementation assessment of post-190 Astra review

Reviewed report: repository `report-astra.md`, SHA-256
`ded9fb9162731d48d90bbc3b3872d495e85b253a240f67b23da338681b1f27f1`.
The evidence supports its immediate recommendation.

The three corrections adopted are:

1. Candidate 190 did not establish a continuing VMID1 GPU fault or GPU
   completion. Its CPU submission counters increased, but capture failed before
   the unchanged Metal probe produced a result. The next run must test execution
   rather than infer it from CPU callbacks.
2. The collector and UART fixes address the demonstrated observation boundary.
   The strict parser and deadlines remain unchanged; runtime reliability is
   still something the next capture must demonstrate.
3. The `GDB=wait`/`slide=0` early rendezvous is removed from executable tools
   and archived as blocked research. The frozen attempt failed OpenCore kernel
   allocation before XNU, and its assumed address omitted the kernel-collection
   `0xe8000` placement. Dynamic `GDB=on` remains available only as a conditional
   follow-up after an actual probe failure.

The next discriminating test is one normally admitted candidate-191/metal-025
GPU run with candidate 190's exact GPU source and known-booting dynamic-slide
configuration. Require complete CR2 capture and run the unchanged native
45-second Metal compute/render probe promptly after native-start gates pass.
A probe result determines the next boundary. Another capture failure returns
work to offline transport measurement; a probe failure requires a same-context
root/prepared/PTB/fault-or-completion chain before any GPU behavior change.
