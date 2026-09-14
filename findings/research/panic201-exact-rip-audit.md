# Candidate 201 exact-RIP and candidates 190–202 driver audit

Date: 2026-09-12

The stronger candidate-195 TLS diagnosis supersedes the older wireSysMemory
causal attribution: [candidate-195 TLS root cause](candidate195-tls-root-cause.md).

Scope: offline evidence only. No VM, GPU, sudo, reset, build, or implementation
change was performed. The panic source is `/home/bogdan/macos-vm/run/serial.log`;
the exact KDK image is
`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`
(SHA-256 `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`).
Disassembly evidence comes from `/tmp/x6000.dis`.

## Verdict

Commit `93c62a5` does not guard the candidate-201 fault. The real fault is a
write through a null internal compute-ring member, not the outer PM4 engine
pointer or its power-up vtable slot. Candidate 202, which contains `93c62a5`,
must not be launched.

The most likely causal chain is:

1. `AMDRTRing::initialize` clears the compute ring's `+0xb0` pointer.
2. The experimental `wrapHwWireSysMemory` has the wrong ABI for the routed KDK
   symbol and returns `nullptr` while VMM `+0x28` is null. Candidate 201 records
   exactly one such apparent 4 KiB deferral, but the misdeclared arguments make
   even that decoded size incomplete evidence.
3. Candidates 198 and 199 report resource initialization failure after the same
   broad null-return guard. Candidate 201 does not expose the intermediate return
   from this particular wire call into ring allocation, so the wrapper is the
   leading producer-side cause rather than a proven direct link or sole cause.
4. An accelerator power-service branch bypass, accidentally reintroduced by
   `a47d878`, forces execution beyond that failure boundary.
5. PM4 startup reaches `AMDGFX10ComputeRing::enable` with `ring+0xb0 == 0` and
   faults at the first store through it.

The minimum safe repair is a rollback of the two success-forcing experiments:
remove the invalid `wireSysMemory` route entirely and preserve the platform
power-service failure branch. Then repair the real cold VMM/handler initialization
contract so native resource allocation succeeds and publishes the ring pointers.
Do not convert missing engine internals, vtables, methods, or allocation products
into success.

## Exact panic resolution

Serial records X6000 at `0xffffff7f9c122000` and the fault RIP at
`0xffffff7f9c1830ad`:

```
0xffffff7f9c1830ad - 0xffffff7f9c122000 = 0x610ad
```

The exact KDK disassembly is:

```asm
AMDRadeonX6000_AMDGFX10ComputeRing::enable:
  6108c  mov al, byte ptr [rdi + 0xa8]
  61092  test al, al
  61094  jne 0x610cf
  6109a  mov dword ptr [rdi + 0xd8], 0
  610a4  mov rax, qword ptr [rdi + 0xb0]
  610ab  xor ecx, ecx
  610ad  mov qword ptr [rax], rcx       ; fault
```

Panic registers are `RAX=0`, `RCX=0`, `RDI=0xffffff9062b6ea00`, and `CR2=0`.
Thus `[RDI+0xb0]` loaded null into RAX, and the store at `0x610ad` attempted to
write address zero. Error code `2` is consistent with a supervisor write to a
non-present page.

The backtrace names the faulting frame exactly as
`AMDGFX10ComputeRing::enable+0x21`. `AMDHardware::powerUp+0x66` appears farther
up as a saved return address. Treating the latter as the RIP loses the two
intermediate frames that identify the resource:

```
AMDGFX10ComputeRing::enable+0x21
AMDGFX10PM4Engine::doStart(bool)+0xb2
wrapHwEngPowerUp+0x1a60
AMDHardware::powerUp+0x66
AMDGFX10Hardware::powerUp+0x1b
wrapGfx10PowerUp
AMDNavi23Hardware::powerUp+0x22
wrapHwPowerUp
AMDGraphicsAccelerator::powerUpHW+0x252
```

`PM4Engine::doStart` makes the data flow explicit. It loads the ring from
`engine+0x70`, calls `initComputeMQD(4)`, then calls ring vtable slot `+0x130`:

```asm
6818c  mov r14, [rdi + 0x70]            ; compute ring
68195  call initComputeMQD(4)
...
6821e  mov rax, [r14]
68221  mov rdi, r14
68224  call qword ptr [rax + 0x130]     ; ComputeRing::enable
6822a  ...                              ; saved return address
```

This matches the last driver log, `PM4 initComputeMQD(ring=4) -> 1`. MQD setup
success does not establish that the ring's host pointer backing exists.

## Producer trace for `ring+0xb0`

The exact KDK establishes both initialization and the producer:

```asm
AMDRTRing::initialize:
  5f5f0  mov qword ptr [rbx + 0xb0], 0

AMDRTRing::allocateMemoryResources:
  5f7fa  lea rcx, [r15 + 0x10]
  5f7fe  mov [rbx + 0xc8], rcx
  ... allocRing / prepareRing ...
  5f867  test al, 1                    ; ring-info policy bit
  5f869  je 0x5f8a3
  5f86b  add r15, 8
  5f86f  mov [rbx + 0xb0], r15         ; publish required pointer
```

`freeMemoryResources` clears `+0xb0` again at `0x5f8db`. Candidate 201 did not
reach a normal teardown before the fault. The observed null therefore means
allocation never published this member, allocation cleanup removed it, or the
ring-info policy did not request it. The serial evidence favors the first case:

```
XV: setMemoryAllocationsEnabled(0) ... m_0x20=0 m_0x28=0 ...
XV: early disable deferred ...
XV: wireSysMemory deferred before VMM channel publication
    phys=0xffffffd88686f000 size=4096
...
XJ: accelerator power-service gate bypass -> ok
XV: setVirtualSpaceReady(1) ... m_0x20=0 m_0x28=0 ...
XJ: PM4 initComputeMQD(ring=4) -> 1
panic at ComputeRing::enable+0x21
```

The routed KDK symbol at `0x4ad44` mangles as
`AMDHWHandler::wireSysMemory(void *, unsigned long long, unsigned int,
IOAccelTask *, unsigned int)`. Including `self`, this requires all six SysV
integer registers: `rdi=self`, `rsi=pointer`, `rdx=64-bit length`,
`ecx=options`, `r8=task`, and `r9d=flags`. The prologue proves the last two by
copying `r9d` at `0x4ad4f` and `r8` at `0x4ad52`.

The wrapper is declared as `(self, uint64_t phys, uint32_t size, void *task,
uint32_t flags)`, only five total arguments. It truncates the 64-bit length to
`edx`, interprets `ecx` options as the task pointer, interprets `r8d` from the
real task pointer as flags, never captures `r9d`, and calls native through the
same wrong prototype. This is a concrete ABI bug independent of the broad null
guard. Returning `nullptr` is also semantically unsafe: it applies to every call
made while VMM `+0x28` is null, regardless of caller or resource identity, and
there is no queue, retry, or later completion. The safe minimum is to remove the
route; retaining it requires an exact six-register signature plus pass-through
tests before any semantic experiment.

## Audit of commit `93c62a5`

The change checks `eng`, `*eng`, and `vtable[0x138/8]` before calling the engine
power-up method. Candidate 201 necessarily passed those checks: the call entered
PM4 `powerUp`, then `doStart`, then a valid compute-ring virtual method. The
faulting null is `[computeRing+0xb0]`, two object levels below the guard.

The `eng == nullptr` branch added inside the callback is dead because
`RaphaelLifecycle::powerUpAll` invokes the callback only when
`engines[index] != nullptr`. Native X6000 also skips absent top-level engines.
The new null-vtable and null-slot branches return `true`, treating incomplete
objects as successfully powered. No test was added with the commit; the existing
`test_engine_lifecycle.cpp` covers loop ordering and cleanup, not Apple object
layout or ring prerequisites. This change can mask initialization failure and
should be reverted rather than extended.

## Candidates 190–202 regression audit

This table is bounded by preserved manifests, current status, Git history, and
available serial. Candidates 190–193 are included for continuity; their older
driver paths were not exhaustively reconstructed because none supersedes the
candidate-194 functional baseline.

| Candidate | Driver evidence | Regression conclusion |
|---|---|---|
| 190 | Run invalid at capture/identity boundary; source digest equals 191 | Driver behavior unobserved; no regression claim |
| 191 | First-submission execution failure | Driver reached submission; not evidence for the later startup-null regression |
| 192 | First-submission execution failure with added VM diagnostics | Same distinction; no startup-null evidence |
| 193 | Inconclusive capture/identity result | Driver conclusion unobserved |
| 194 | Source `52c7517`; probe run `1f0649...` completed four command buffers, checked 196,608 compute values and 4,096 render pixels | Strongest functional baseline. Overall verdict remained INCONCLUSIVE from capture loss, so it is not a fully authenticated qualification/recovery run |
| 195 | Same functional boot arguments as 194 except nonce; panicked in native `wireSysMemory` during cold allocation-disable | Demonstrated startup regression/non-repeatability. The 194→195 source diff adds diagnostics and later KIQ work; no direct source line is proven to cause this pre-power-up fault |
| 196 | Added cold `setMemoryAllocationsEnabled(0)` early return | Harness did not observe driver boundary in the cited run; repair unproven |
| 197 | Same driver source as 196; real observed run still made an invalid dispatch after the skipped disable | Demonstrates the cold-disable skip did not repair the underlying handler/resource contract |
| 198 | Added broad `wireSysMemory` null return | Demonstrated that the panic moved to `Failed to init HW Acelerator resources`, followed by the known cleanup null panic. This suppressed a crash but created/propagated allocation failure |
| 199 | Added start-failure cleanup branch patch | Cleanup panic removed; accelerator still stopped cleanly at the power-service failure. No Metal submission |
| 200 | Bypassed power-service failure and retained forced VMM enable | Demonstrated invalid dispatch/`commit_pte` panic during forced enable; unsafe experiment |
| 201 | `a47d878` gated forced VMM enable but accidentally reintroduced the removed power-service bypass; broad wire wrapper remained | Demonstrated ring `+0xb0` null panic after forced advance into PM4 start |
| 202 | Adds `93c62a5` skip-as-success checks; build/staging evidence only | Does not cover actual RIP and can hide incomplete engines; invalidate before hardware |

The candidate-194 and candidate-195 manifests use the same functional boot
arguments (`rgpu=0xfffa5981`, `rgpuvmm=3`, `rgpumem=1`, `rgpuptb=2`,
`rgpumqd=2`, `rgpuhybrid=1`, `rgpusubmit=1`, `rgpuvmroot=5`); only the recovery
nonce differs. Candidate 201 keeps those flags and omits `rgpuvmmforce=1`, but
its compiled source still applies the power-service branch patch whenever XJ is
enabled. Thus disabling forced VMM enable isolated one candidate-200 crash while
leaving the unsafe control-flow bypass active.

Candidate 195 also introduced `thread_local ActiveMapCommitWindow`; the
candidate-201 binary exposes `__thread_vars`, `__thread_bss`, and an undefined
`__tlv_bootstrap`. The kext did load, and the observed panic did not occur in
that path, so this is an independent kernel TLS/ABI validation risk rather than
an evidenced cause of the candidate-201 fault.

## Ranked causes and minimum next test

1. **High confidence, directly proven:** the `wireSysMemory` wrapper has the
   wrong ABI and its broad guard turns a required wire into `nullptr` with no
   deferred completion. Remove the route. Any later wrapper must first match the
   six-register KDK ABI exactly, then remain observation-only until the real
   handler/VMM producer is understood.
2. **High confidence, directly actionable:** the power-service bypass permits
   engine startup after earlier initialization failures. Restore the native
   failure branch; the exact candidate-201 intermediate failure return remains
   uncaptured.
3. **Medium confidence:** the cold VMM disable crash and missing channel are a
   symptom of incorrect VMM/handler initialization ordering. The early-disable
   return avoids one call but cannot construct either the VMM DMA channel or the
   ring backing.
4. **Rejected for this panic:** outer engine pointer/vtable/power-up-slot null.
   The exact call chain proves those were usable.

Bounded Luna implementation brief after coordinator review:

1. Revert `93c62a5` in `wrapHwEngPowerUp` and add a fixture asserting incomplete
   engine metadata fails closed and triggers cleanup exactly once.
2. Remove the power-service lookup patch that `a47d878` reintroduced. Add an
   offline byte-pattern test proving the native conditional branch remains.
3. Remove the `wireSysMemory` route. If a later diagnostic route is justified,
   give it the exact `(self, void *, uint64_t, uint32_t, IOAccelTask *, uint32_t)`
   ABI and verify argument forwarding before making it observation-only. Log the
   caller offset, all five native arguments, native result, VMM slots, and
   relevant ring state without changing the result.
4. Add an exact-KDK static regression that resolves the candidate-201 RIP to
   `0x610ad`, verifies bytes `48 89 08`, and models the required producer
   invariant: PM4 power-up is not admissible unless compute-ring `+0xb0` (and
   the following `+0xc8` store target) are non-null.
5. Before hardware, compare the binary/source/boot arguments with candidate 194
   and complete the mandatory post-three-attempt Astra review. The next live
   discriminator should stop cleanly at the native power-service failure unless
   the real resource producer now succeeds; reaching PM4 with a null ring member
   is an immediate abort, never a success path.

Recovery acceptance must still require the authenticated project receipt. A
stopped QEMU process, `vfio-pci` binding, device accessibility, and absence of a
host kernel fault are useful host-safety evidence but do not prove graphics-ring
retirement or repeatable recovery.
