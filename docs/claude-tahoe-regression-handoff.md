# Claude handoff: fix the macOS26 Raphael GPU regression

> **Resolved 2026-10-14 (candidates 502-506).** Both retained failures had one cause: Apple's
> GFX10 Metal defaults oversubscribe the GE parameter cache for Navi2x
> (`GE_PC_ALLOC = OVERSUB_EN | 512 lines`) while Raphael has 256 lines, which deadlocks
> attribute-heavy late-Z draws (Weather's map, the Memoji picker); the resulting GPU
> restart storms wedged VCN, which explained the encoder stall. The driver now clears
> `allowGePcAllocOverSub` dynamically in every Metal client. Evidence:
> [tahoe-gfx-deadlock-20261014](../findings/research/tahoe-gfx-deadlock-20261014.md).
> The text below is the original handoff, kept for history.


User instruction: fix the root cause in the driver. Latest macOS15 worked for the
user; latest26 freezes. Preserve native Metal and hardware video capabilities.
Do not solve this by disabling CoreMedia, HEVC, apps/widgets, or using software
encoding. Support macOS updates dynamically; avoid OS-build allowlists and guessed
offsets. Work is currently paused; begin hardware experiments only when the user
explicitly resumes/authorizes your investigation.

Workspace: /home/user/src/macos-raphael-igpu is a stale detached checkout.
Read its AGENTS.md, /home/user/.codex/skills.md and
/home/user/.codex/memories/raphael-evidence-lessons.md. Use the current status at
/home/user/macos-vm/run/worktrees/dev-delivery/status.md and the candidate494
status. Read docs/host-safety.md and docs/running-an-experiment.md before hardware.
Develop in a new candidate worktree under ~/macos-vm/run/worktrees, not ~/src.

Latest exploratory branch/worktree: candidate494 at
/home/user/macos-vm/run/worktrees/candidate-494. It starts from candidate490,
without unverified491-493 workarounds. Build source22a52be949e0dee37cd352d4f5addeef56be0e2c,
build6d37de612f5f49b1bad5f52db4639b59. Current dev source remains e276f1b;
no root-cause GPU fix has been delivered. Candidate494 also adds an uncaptured
startup-cancellation recovery admission path: audit this separately, preserving
all reset/queue/PSP/identity gates. Host suite1626 passed,8 skipped.

Two failures need attention:
1. Candidate493 earlygate: run859837b1298120ac07a14850eb389c37, results
~/macos-vm/run/candidate-493-attempt-earlygate-results. Weather PID496, Metal VMID4,
is first pending graphics CB BEFORE any encoder creation. No HEVC decode context
exists. Graphics RPTR1bdb1/WPTRbc000, IB4000e0000, CP_STAT94038600,
STALLED_STAT2=10002, VM_FAULT_STATUS0. pm4-command-buffers.txt has zero rejected
checksums. Later VideoContext teardown holding a device mutex is downstream.
Deferred page-table reads occurred after restart/VMID reuse: entry0 is not proof
that the original mapping was absent. Candidate494 freezes context registers to
avoid that misinterpretation.
2. Candidate494 vmabi4: run0b504695909175c6fd2974d807c3c1bb, results
~/macos-vm/run/candidate-494-attempt-vmabi4-results. With original CoreMedia prefs
and Sunshine hardware encoding restored, desktop Metal probe passes while the
GUI freezes. Graphics ring advances/drains; first pending client VTEncoderXPCServ
PID808 is Video, channel15 VCN0EncLLQ stamp1. Earlier native cosWaitForFunc timeout
callback is25G241 HWLibs _wait_for_vcn_response at+8036e. The27-byte callback reads
engine pointer atrequest+0, segment+8, register+c, expected+10, mask+14. Actual
failed request fields and caller are still missing: capture those next, without
extra unsafe MMIO or forcing completion. Full all-process-spindump.txt retains
IOServiceTerminateThread0x6f in VideoContext teardown holding the accelerator lock.
Do not assume this VCN failure explains the earlier Weather graphics failure.

Ruled out/scoped evidence:
- First VM requests1..8 in494 have raw reprogram byte1 and repaired physical roots.
  Native26 tests bit0, our helper ==1: a mismatch exists for noncanonical bytes,
  but it is not supported as the observed cause here.
- Full guarded MMHUB table repair succeeds on15 and26.
- Native encode3_0_submit_frame fields/arithmetic match; disassembly changes shown
  are relocations. Offline excerpts: ~/macos-vm/run/c494-native-vm-audit.
- Native images: ~/macos-vm/run/upload/{24H32,25G241}-SystemKernelExtensions.kc.
  machosyms.py under ~/macos-vm/run/kc resolves exact function offsets.
  Current26 userspace TEXT: ~/macos-vm/run/upload/compat-e02dec4d05364d7093e33ea1293ef9db/{metaltext,vatext}.
  Latest15 TEXT files are in the same upload parent with24H32 prefixes.
- Retained matched latest15 benchmark results are in candidate-490-attempt-perf15v2r1-results.
  Small/offscreen benchmark success is not a controlled comparison of all desktop/media workloads.
- Earlier CoreMedia transfer-disable experiment changed the first failing workload
  but still froze; HEVC gating and SDMA retry did not establish a fix.

Current machine: no VM/experiment running. Active disk ~/macos-vm/mac_hdd_ng.img
is26.7.1/25G241; retained rollback/macos-15.8.1-24H32.img is latest15. Do not test
older releases. SSH when running: ssh -i ~/macos-vm/vmkey -p50922 user@127.0.0.1.
Root guest relay ~/macos-vm/gx must never overlap harness commands; use only after
results/interactive-ready.json. Never handle or log Apple account credentials.
Apple sign-in patches and authorized SSH key are already installed; preserve them.
Sunshine original15 config/app were copied and checked. Native Screen Sharing is
enabled; both remote paths can block behind the GPU/device lock.

Safety: GPU0000:7b:00.0 is vfio-pci, power/control=on. Never rebind to amdgpu within
this boot. No host sudo. Keep one hardware owner. All experiments through cycle.py,
max6000s, native identity-bound shutdown/supervised cleanup, immutable receipts.
Use explicit experiments/pins-igpu-display-v15.json to match current QEMU image
sha256:38193017b44e79314406622a7c5db670b1724b45a6687a8dfe00440169c113e1.
Latest ordinary recovery for494 is incomplete/non-authorizing. The separate
~/macos-vm/run/candidate-494-vmabi4-requalification.json validates authorizes_launch=true,
errors=[], kernel_faults=[] on recorded boot2e377991-b6d2-4fe5-81dd-fd6afe9999f7.
Re-inspect live state and receipt binding before any launch. Same-boot reuse is
automatic from the latest valid receipt. Do not pass this receipt to the unrelated
legacy --noqueue-reuse flag. Do not invent receipts, remove ledger reservations,
skip completion waits, or fake GPU stamps.

Deliver a driver fix supported by the first failing native operation and a matched
latest15/latest26 workload. Verify correct pixels, sustained interactive desktop,
hardware video frames and remote display, and repeatable shutdown/recovery. Report
function, capture, cleanup and qualification independently. After a verified
milestone update README/status/ROADMAP/current docs, integrate and push dev and
wait for exact-commit hosted test/build CI. Do not publish main. Xcode installation
and QEMU close confirmation remain pending, secondary to a stable desktop.
