# Astra review after candidate 190

2026-09-10. Mandatory review after three actual GPU attempts since the
post-186 review: 187, 188, and 190. The unresolved execution streak remains
11. Candidate 189 stopped before GPU exposure. This review resets neither
that streak nor the host-boot launch budget, currently 2 of 3 consumed.

Scope: offline inspection of current status, implementation, tests, frozen
captures, cached primary Linux sources, and the exact 24G830 kernel binary.
Only this report was written. No VM, device, sudo, reset, recovery, build, or
test execution occurred. Existing test results were inspected, not rerun.

**The next GPU experiment should obtain complete CR2 capture and run the
existing Metal compute/render probe with candidate 190's GPU implementation.**
Do not spend that experiment qualifying the new early-debugger design. The
known VMID1 root-eligibility defect was corrected before 190; 190 then lost
capture before a Metal probe could establish whether execution improved.
Its missing VMID1 fault record and increased CPU submissions are promising
observations, not proof of success or a continuing identical GPU fault.

The immediate demonstrated blocker is the observation pipeline. The remaining
GPU failure boundary after the root correction is unknown.

## What the last batch established

| Attempt | Useful observation | Failed or unestablished boundary |
|---|---|---|
| 187, run `a89f6fadf08d2f6bf55a53e6c7b4196c` | Explicit guest PCI slot restored target identification, ownership, KIQ, and engines after 186's startup regression | VMID1 fault `0x101b3a`, VA `0x400580000`; incomplete CR2; no Metal probe |
| 188 continuation, run `cb1d0aadd8186205d867a23fe175c336` | Same VMID1 fault; entry-update GDB breakpoint reached; normal cleanup succeeded | Root policy still excluded VMID1; CPU-number pairing rejected the next stop; incomplete CR2; outgoing arguments unestablished |
| 190, run `3ffc5f3dbec53665214863ed91fee0e7` | Client-root policy includes VMIDs 1–15; CPU submit calls reached `660/660`; no retained VMID1 fault record found in serial | CR2 incomplete; late GDB obtained no selected wrapper hit; no probe result; original verdict INVALID |

The post-186 review recorded eight unresolved attempts. These three exposures
reconstruct eleven without counting prelaunch failures, GPU-less qualifications,
builds, parsing, or recovery as GPU cycles.

Candidate 190's serial has `submit=660/660/0` at line 4656 and mapping/prepare
failure counters of 6/2. These are CPU callbacks, not completed GPU command
buffers or a workload-normalized performance comparison with 188. Its retained
fault-capture summary at line 2163 rejects a non-VMID1 fault. Incomplete capture
cannot establish that no later fault occurred. Equally, an old 188 fault must
not be reported as an observed 190 failure.

The later recovery is valid separate evidence. I recomputed the canonical
schema-6 receipt hash and checked its recorded boot/run binding,
`status=recovered`, and `authorizes_launch=true`. Coordinator and independent
review record successful full validation, queue retirement, graphics cleanup,
SDMA shutdown, and PSP destruction. The wrapper's failed result came from
omitting the manifest in its second validator; it does not negate completed
cleanup. **Do not repeat recovery.** The original invalid capture and failed
original `recovery.json` stay frozen. See
[the recovery audit](findings/research/2026-09-10-candidate190-recovery-independent-review.md).

## The GPU hypothesis improved; the tests initially encoded the wrong policy

The former root helper excluded every client VMID except 2 even though the
observed fault was VMID1 with root `0xf40b6ff000`. The audited conversion is:

```text
MC root            0xf40b6ff000
framebuffer base   0xf400 << 24
physical offset    0x0840 << 24
physical root      0x084b6ff000
```

Primary source supports this direction. In the cached Linux stable `v7.2.3`
sources, `gfxhub_v2_1_setup_vmid_config` programs client contexts 1–15;
`amdgpu_gmc_pd_addr` obtains the root through the ASIC PDE callback;
`gmc_v10_0_get_vm_pde` converts non-SYSTEM directory pointers using MC-to-physical
arithmetic. The flush routine emits encoded PTB halves before a VMID-specific
invalidate request and ACK wait. I inspected these functions directly in the
cache pinned by [the source comparison](findings/research/2026-09-10-linux-vm-exact.md).

The current helper retains hub, client-VMID, exact reprogram predicate, SYSTEM,
attribute, aperture, and overflow checks. Its regression fixture uses the
captured VMID1 root and independently derived expected address. This correction
has stronger support than tests that merely asserted VMID2-only behavior. It
still does not prove that native preparation, PTB programming, invalidation,
table writes, and GPU execution all used that root in 190.

Two earlier reasoning shortcuts must stay retired:

- The CPU walker deliberately translates MC table pointers into their CPU
  physical alias. A readable PDE and zero at leaf index 1408 in 187/188 did not
  establish that the GPU fetched the root first. Treating that zero as the
  first GPU failure skipped the root-domain defect.
- Apple's captured BFS4/TF hierarchy is not Linux's BFS9 hierarchy. Linux
  establishes address-domain and sequencing rules, not permission to copy its
  geometry or reinterpret an unsupported TF walk as a missing leaf.

If the post-correction probe fails, obtain a same-context chain: original root,
outgoing native root, prepared words, actual PTB, and subsequent fault or
completion. Global mode-4 conversion counts and VMID2-only observations cannot
substitute for VMID1 correlation. No reviewed evidence justifies another
speculative PTE flag, geometry, allocation, or invalidate-register change
before testing actual Metal execution.

## Capture failed upstream of the strict parser

Candidate 190's 362,575-byte `critical.txt` has complete END records only for
snapshots 0–3. Serial reports transmission failures for snapshots 4–13. Later
incomplete snapshots contain records beyond the last certified prefix;
discarding them would hide unknown later state. Strict refusal is correct.

The [capture audit](findings/research/2026-09-10-candidate190-capture-audit.md)
identifies synchronous per-receive `fsync` in the old collector as a concrete
socket-drain stall mechanism. Its cited QEMU 10.1.2 transmit path can leave
THRE clear while the nonblocking backend is backpressured. Failed attempts
4–12 each emitting approximately 36–41 KiB are consistent with a finite-buffer
boundary. That is a strong transport hypothesis, not a measured attribution of
each timeout to writeback. I inspected collector code and fixtures; I did not
independently download or inspect QEMU source during this offline review.

The coalescing sync worker removes the direct synchronous `fsync` dependency
from socket draining. Generation accounting requires another sync for bytes
written during a sync; short writes and socket/sync errors remain failures.
But writes still occur synchronously in the draining thread. Concurrent writes
and `fsync` on the same filesystem/inode may contend; mocked sync tests do not
establish real Btrfs/QEMU throughput. Do not restrict that residual uncertainty
to catastrophic filesystem failure or claim runtime reliability yet.

The UART fake-I/O tests usefully disprove an overstatement: elapsed time beyond
2 ms is insufficient to fail a byte if the next THRE read is ready. Failure
requires THRE still busy at the timeout check, or an expired independent
snapshot deadline. These fixtures identify possible mechanisms, not the
historical host schedule.

Existing collector fixtures establish that a blocked mocked sync no longer
prevents the next receive and that overlapping generations are synced again.
If further qualification is needed, replay a large captured CR2 payload through
a real bounded Unix socket with delayed sync and check exact bytes and final
durability. That can run without a GPU. If real write-side stalls recur, first
measure them; then consider separating socket draining from a bounded writer
queue with explicit overflow failure. Do not relax UART, capture, or exposure
deadlines to conceal the mechanism.

## The early debugger draft repeated already investigated mistakes

`GDB=on` does not stop vCPUs. Waiting for a serial kernel mapping and Raphael
build marker before attaching cannot guarantee the first prepare call is
intercepted. The corrected CID-derived path fixes one delay, not this race.
The 190 transcript authenticates the kext and arms the wrapper but contains no
selected wrapper hit. This is missed observation, not proof of no wrapper call.

The proposed `GDB=wait` plus `slide=0` design then assumed both that the guest
would boot and that kernel text would equal KDK link text. Neither premise was
qualified. Its tests explicitly expect `0xffffff8000200000`, preserving the
relocation error rather than detecting it. Other passing tests cannot validate
that assumption.

### Exact attribution of the old zero-slide failure

Directory
`/home/bogdan/macos-vm/run/gdb-qualification-20260910T160000Z/vm/run/`
contains copied older metadata and an appended serial log:

| Evidence | Earlier copied run | Actual debugger qualification |
|---|---|---|
| Launch metadata suffix | `64d644c3f891453d93445d8938de4ca5` | `67f42fefe7bb473da96ee014eb122dc1` |
| CID prefix | `268701270b6f` | `a25dfcc6c1db` |
| Start UTC | 14:17:15 | 15:50:40 |
| Firmware serial timestamp | 14:17:26 | 15:51:09 |
| Serial segment | Lines 1–1490 | Starts at line 1491 |

The earlier launch's readiness path explicitly names
`headless-lilu-qualification2-20260910T141530Z`. Its Darwin lines 68/81 and
dynamic slide `0xa000000` are inherited evidence. They do not show the
zero-slide debugger attempt booting. The appended segment has no Darwin or
successful HANDOFF-to-XNU and repeatedly returns to OpenCore after StartImage
failure. This resolves the apparent contradiction using launch provenance.

The appended boot.efi log identifies the immediate failure boundary:

```text
EB.MM.AKM: Err(0xE) <- EB.MM.MKP
EB.LD.DS64: SEG! __TEXT_EXEC
EB.LD.DS64: 0 <- EB.MM.AKMr2 0xa14000 0xffffff80002e8000
KMA:P: 0x200000 0x2e8000
KMA:R: 0 0
STOP: 0x16
```

The emitted memory map has conventional memory from physical `0x2e8000` only
through `0x800000`, followed by non-conventional regions. The requested
`0xa14000`-byte span would extend through `0xcfc000`. The observed boundary is
low-memory kernel allocation before Darwin, consistent with forcing zero slide
into that map. Three appended menu attempts repeat the allocation failure.

The GDB script also requested a software breakpoint at an unmapped kernel
address and got `Cannot insert breakpoint`. That is independently wrong. No
successful breakpoint-byte write is evidenced; later boot-menu retries after
detach still failed. The corrected qualification changed multiple inputs, so
do not claim a controlled proof that `slide=0` alone caused every difference.
The actual loader failure is sufficient reason to abandon this zero-slide
recipe without another GPU exposure.

### Correct relocation and future deterministic qualification

I reparsed the pinned kernel Mach-O and freshly disassembled `OSKext::start`.
KDK UUID is `f6a1b3d41ebb3628a1c589506c51ddec`; link `__TEXT` is
`0xffffff8000200000`; `OSKext::start(bool)` is `0xffffff8000970230`.
Disassembly verifies the `OSKext+0x50` kmod pointer, address/size at kmod
`+0x9c/+0xa4`, and the indirect start callback at function `+0x248`.
The current-kext rendezvous is a sound candidate boundary after address and
runtime qualification.

Candidate 190 gives the missing arithmetic:

```text
runtime kernel TEXT      0xffffff8002ae8000
reported KASLR           0x02800000
unslid collection TEXT   0xffffff80002e8000
KDK link TEXT            0xffffff8000200000
collection placement     0x000e8000
total symbol relocation  0x028e8000
historical OSKext::start  0xffffff8003258230
```

The successful `gdb-runtime-fix-20260910T203000Z` capture already used total
relocation `0x1b4e8000`, hit `mach_absolute_time`, single-stepped, and detached.
The source-debug qualification separately observed the same `0xe8000` placement.
This is repeated exact-build evidence, not a universal constant across other
kernel collections or media.

For future early capture, prefer a **qualified nonzero fixed slide on exact
private media**, with authenticated collection mapping. Choose a range supported
by the guest memory map; 190's observed `0x02800000` placement is a qualification
input, not a guarantee for all topologies. Verify boot-argument units and the
actual reported slide rather than inferring addresses from an option alone.

Use `GDB=wait` to attach before execution. Install a hardware rendezvous at
link-symbol plus the complete relocation; authenticate kernel UUID and bytes
at the stop; select the current Raphael kmod by exact name/UUID; arm the wrapper;
remove the loader breakpoint. Qualify the reset-to-long-mode sequence in a
fresh GPU-less run with empty capture paths and actual QEMU/KVM behavior.
Confirm the current Raphael start boundary and subsequent plugin code are
reached, then detach and verify boot. Mock-script tests cannot establish that
a hardware breakpoint survives early boot or that the 512-stop cap fits.
Avoid unbounded arrays of candidate-slide breakpoints.

No deterministic early method has yet been demonstrated by the reviewed
evidence. Archive the unqualified implementation draft, retain its research,
and keep this work separate from the next functional GPU test.

## Revised next batch

This is a conditional sequence, not a commitment to consume three launches.
Only one budget slot remains on the current boot; it still needs normal
reviewed admission and fresh host checks.

1. **Next GPU attempt: execution after capture repair.** Preserve exact 190 GPU
   source and known-booting dynamic-slide topology. Include the reviewed
   collector correction and CID path fix. Revise 191's primary question to
   whether the corrected client roots support the existing Metal probe once
   complete capture is available. Remove `slide=0` and the unqualified early-GDB
   requirement; keep GDB available in its working mode. Retain identity,
   native-start, complete-capture, time-fit, and recovery gates. Start the probe
   promptly when they pass, rather than spending the exposure waiting for an
   old initialization breakpoint that may already have passed.
2. **Follow the first demonstrated boundary.** Repeated capture loss means
   investigate transport without the GPU before another exposure. Complete
   capture plus probe failure supplies the next execution boundary; prepare
   GDB for that actual failure. A VMID1 fault calls for the original/native/
   prepared/PTB chain. Completed work with wrong values calls for resource
   visibility/synchronization evidence. No selected fault and no completion
   still requires ring/fence evidence, not speculative geometry changes.
3. **After a full probe pass, advance toward the real goal.** Preserve its
   correctness evidence and test desktop presentation and required crash/
   QEMU-close cleanup under existing finite procedures. Compute/render success
   is meaningful progress but does not itself establish desktop acceleration
   or repeatable crash recovery. If execution remains unresolved for three
   actual attempts after this review, refresh status and review again before
   a fourth. Successful review never increases a boot's exposure allowance.

The unchanged probe already provides a strong discriminator: three randomized
compute rounds check 196,608 values; a 64×64 private texture is rendered,
blitted, and synchronized into managed memory; all 4,096 pixels are verified.
At least four completed command buffers and the nonce-bound passing result
are required. Its synchronization means failure can involve paging or readback
as well as shaders. A complete pass is more informative now than another
CPU-only root snapshot.

GDB helps within a run only when prepared, bounded, and leaving time for probe
and cleanup. CPU stops do not freeze the passed-through GPU; debugger-induced
timing must not be labeled a natural timeout reproduction. Pair entry/native/
return using captured call-frame identity. QEMU CPU numbers are not XNU thread
identities. The 188 mismatch proved neither CPU migration nor an argument bug;
it established that the old pairing rule rejected the next stop before the
wanted outgoing arguments were captured.

## Documentation and evidence

At review time status begins with successful recovery but retains present-tense
claims below it that no receipt exists and hardware is blocked by failed
recovery. The capture audit also retains the superseded four-attempt cadence.
Replace or explicitly date these statements in the working summary; preserve
archived evidence. Such contradictions can drive unnecessary recovery or
misdirected debugger work.

The required methodological corrections are concrete: compare actual run
boundaries; derive test expectations from captured values and primary
implementation; qualify debugger and transport plumbing without GPU exposure;
run the existing functional probe when its real prerequisites pass. Larger
suite counts or more admission machinery do not identify the unknown GPU
execution boundary.

Recomputed SHA-256 values:

| Evidence | SHA-256 |
|---|---|
| Candidate 190 `critical.txt` | `17c071a1463a578913cfed84278d9b4ad069ae8b9966e46914bd6af6289be13a` |
| Candidate 190 `serial.txt` | `ce074323b4c746d05f26e7b22d6135caa2aa2fe51b7b3520cef0b64765067bf9` |
| Canonical 190 recovery receipt | `82560e48da2e6fb4300f5b0095e821d3da404d170108fd891ca7824aad49967a` |
| Qualified isolated KDK executable | `04a501246caf768356f4090a8fd662daf5bbc949993353526c66771f5ba1d8e4` |
| Archived preceding Astra report | `2424d478ec5cf829adc2cb361bd6f0c9768aa184db580674514ba4bff99061d1` |

The preceding report was verified byte-for-byte against its archive before
replacement, at
`findings/research/astra-reviews/2026-09-10-200942-pre190-review/report-astra.md`.
Candidate 190 captures are under `/home/bogdan/macos-vm/run/metal-024-190`.
The receipt is under
`/home/bogdan/macos-vm/run/vfio-recovery/3bca3e47-1f28-4f78-af00-5dbf76b00620/3ffc5f3dbec53665214863ed91fee0e7.json`.
The isolated kernel is
`/home/bogdan/macos-vm/run/gdb-source-kext-prep-20260910T204500Z/kernel.symbols`.
No Claude review ran here. Coordinator and implementation-agent assessment must
precede the revised test batch. This report extends no budget, grants no retry,
and replaces no recovery receipt.
