# Tahoe desktop regression investigation

The latest 15.x retained performance run uses candidate490 and advances its
graphics ring during the measured workload. The failing26.x unlocked desktop
adds Weather and account/media activity; those workloads are not controlled
by the earlier matched offscreen benchmark. The user reports15.x was usable.

Candidate493 earlygate first pending client is Weather PID496/VMID4, before
encoder creation; disabling HEVC selection did not prevent the graphics stall.
Native video-context teardown later holds the accelerator device mutex while
waiting for GPU timestamps. This blocks WindowServer resource creation and
Sunshine device opening. The teardown is downstream of this graphics failure.

Candidate493 transfer2, with CoreMedia transfer disabled, remains unusable:
later VTEncoderXPCServ work stalls. Its shutdown was forced; immutable ordinary
recovery is incomplete. Separate MODE2/noqueue requalification authorizes launch.
CoreMedia original absent preference and Sunshine hardware encoder are restored.

Native24H32/25G241 comparison in ~/macos-vm/run/c494-native-vm-audit shows:
- getPDEValue and updateContiguousPTEsWithDMAUsingAddr are byte-identical.
- getPTEValue comparison operand order changes with equivalent unsigned condition.
- prepareVMInvalidateRequest retains hub stride0x358, table offset0xba0 and
  input layout0x28, but changes reprogram byte predicate from ==1 to bit0 set.
  Our observation/root-repair helper assumes ==1. No noncanonical live request
  has yet been established; this is a hypothesis, not a demonstrated hang cause.
- Hub register-table population changes loop generation; live complete guarded
  MMHUB repair reports success on both builds.

Candidate494 starts from490 and adds bounded read-only diagnostics: first client
request per VMID with raw reprogram byte, plus frozen VM register snapshots at
the first graphics-hang capture. Deferred output reports whether each context
still matches, to distinguish original mapping from later VMID reuse. No engine
reset, completion substitution, feature disabling or software fallback is added.
The root cause remains unresolved.

Raw evidence stays in the local run directories, including private process
spindumps. No full desktop qualification or milestone delivery is claimed.

## Candidate494 vmabi4 result

Run0b504695909175c6fd2974d807c3c1bb restores all normal hardware policies.
The desktop Metal probe passes while the unlocked desktop is unusable. VMIDs1..8
first requests carry byte1 and have repaired roots; no support for a noncanonical
reprogram byte here. VTEncoderXPCServ owns pending Video channel15/LLQ stamp1.
The earlier native cosWaitForFunc callback is _wait_for_vcn_response at25G241
HWLibs+0x8036e. Its bounded27-byte routine reads the request's engine pointer,
segment, register, expected value and mask. The actual failed request fields
remain missing; capture them before changing the handshake or queue behavior.
Encode3_0_submit_frame retains the same object fields and arithmetic in15/26;
its disassembly differences are relocated references and branch/call targets.
Forced shutdown and complete separate MODE2/noqueue recovery are retained.
