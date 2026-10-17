# Candidate 1.0.155: first real execution test failed

Container started at 2026-09-07T18:46:57.271229493Z. The guest loaded RaphaelGPU
1.0.155 with `rgpumqd=2 rgpuptb=1 rgpumem=2 rgpuvmm=3 rgpu=0xfffa5981`.
Candidate Mach-O SHA-256: `64eb21ef046cd33d99c3e14c4f20fcbfce9bf7f04dc0f5ae9c544b986e053a07`.

The native probe found AMD Radeon Navi23, advertised Metal 3, and compiled the test
shaders. Its first compute command failed with status 5 and MTLCommandBufferErrorDomain
code 1, underlying `e00002bd` (`kIOReturnNoMemory`). Zero compute elements and zero
rendered pixels were verified. This is a failed execution test, not acceleration.

The guest's persisted unified log reports `Stamp Timeout for KIQ Submission!` at
21:47:52.406 local time (UTC+03:00). Serial capture stopped at 21:47:21, before the
XQ2 preparation diagnostics. Therefore this run cannot establish from captured registers
whether the MQD/EOP preparation completed or whether EOP readback changed.

Both the detached serial process and the detached 180-second watchdog disappeared
after the launch tool exited. Their shell background lifetime was inadequate in this
execution environment. The exact container was explicitly stopped by the operator agent;
no host crash occurred. A GPU-less guest was then used to recover the persisted log.
The next GPU run requires durable supervision and capture verified outside the launch
caller's process lifetime.
