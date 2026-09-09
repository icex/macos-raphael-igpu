# Review of the reported backing-memory diagnosis

Date: 2026-09-10

This review checks `report-astra.md` and `report.md` against the exact macOS 15.7.9 / 24G830 binaries and the preserved candidate178-A/B evidence. The result is narrower than either report's strongest proposed fix:

- Astra's two-stage superclass failure path is correct. `map+0x18` is exactly an `IOAccelMemory *`, and the captured `0xb13` map state takes a path that can fail during backing preparation before X6000's PTE commit callback.
- The concrete video-memory backing implementation is now resolved through its actual 24G830 vtables. Its wire path reaches `AMDAccelVidMemory::allocPhysical` at X6000 file offset `0x3aa76` and propagates its Boolean result.
- The claim that X6000 passes an inverted interval to `IOAccelMemoryAllocator2::init_pool` is false. The framework overload uses `(total, reserveStart, reserveLength)`, while X6000's two-argument calls use `(start, length)`. Swapping the 512 MiB and 256 MiB fields is not supported by that disassembly.
- The 240 MiB cap remains a strong historical regression correlate and the old fixed recovery range has a real ownership defect. Neither fact proves that restoring capacity alone fixes Metal. The proposed experiment that leaves recovery scratch inside Apple's live heap is unsafe and must not be used.
- The earlier candidate179 commit-correlation design cannot reliably name the final failed retry. A direct, append-only observer at the concrete `allocPhysical` boundary is simpler and preserves more defensible evidence.

No GPU, VM, VFIO, MMIO, build, or recovery operation was used for this review.

## Exact inputs and reproducible framework extraction

The private offsets in this note apply only to these binaries:

| Input | SHA-256 |
|---|---|
| `/home/bogdan/macos-vm/kdk/KDK-24G830.dmg` | `9e2bb18ed726b805ffc009db30bc4bfe7539ed138746165600b0fd5a77562ed4` |
| `AMDRadeonX6000` | `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e` |
| extracted `IOAcceleratorFamily2` executable | `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35` |

The inspected X6000 executable is:

```text
/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/
AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000
```

The framework member was extracted without mounting the DMG. These commands reproduce the extraction with the checked-in local `pbzx.py` decoder; `cpio` scans the payload but writes only the requested member:

```sh
scratch=$(mktemp -d /tmp/kdk-ioaf.XXXXXX)
7z e /home/bogdan/macos-vm/kdk/KDK-24G830.dmg \
  -o"$scratch" 'Kernel Debug Kit/KernelDebugKit.pkg'
7z e "$scratch/KernelDebugKit.pkg" -o"$scratch" 'KDK.pkg/Payload'
mkdir "$scratch/root"
(
  cd "$scratch/root"
  python3 /home/bogdan/macos-vm/kdk/pbzx.py "$scratch/Payload" | \
    cpio -idm --quiet \
      './System/Library/Extensions/IOAcceleratorFamily2.kext/Contents/MacOS/IOAcceleratorFamily2'
)
sha256sum "$scratch/root/System/Library/Extensions/IOAcceleratorFamily2.kext/Contents/MacOS/IOAcceleratorFamily2"
```

The reviewed temporary executable was `/tmp/kdk-forensics.HZuAtO/IOAcceleratorFamily2` with the same digest. The extraction path is disposable; the KDK digest, member path, executable digest, and reviewed instruction intervals below are the durable anchors.

## Exact superclass path

### `map+0x18` is the backing `IOAccelMemory *`

`IOAccelMemoryMap::init(IOGraphicsAccelerator2 *, IOAccelTask *, IOAccelMemory *, unsigned)` begins at IOAcceleratorFamily2 `0x5267e`. Its relevant interval is `0x5268f..0x52705`:

1. The fourth object argument in `RCX` is saved at `0x5268f`.
2. It is stored at `[map+0x18]` at `0x526ea`.
3. That object is retained at `0x526f2`.
4. The same object is passed to `IOAccelMemory::add_mapping` at `0x52705`.

This proves the declared base type. It does not, by itself, identify the live subclass. The X6000-created video-memory subclass is established separately below.

`IOAccelMemory::getLength` at framework `0x2d4c` returns `[this+0x40]`. Therefore backing `+0x40` is the exact length field used by the direct observer.

### Base map preparation has two rejection boundaries

`IOAccelMemoryMap::prepare` starts at framework `0x52c08`. With prepare count `[map+0xc] == 0` and map flag bit `0x4` clear, it enters cold helper `0x58308`. Candidate178's retained flags `0xb13` meet that condition.

The cold interval `0x58308..0x58343` has this control flow:

```text
backing = [map + 0x18]
backing->vslot_148()
if false: publish handled=false and return without commit
commit_pte(map)
if false: publish handled=false and return
increment [map + 0xc]
backing->vslot_150()
publish handled=true
```

The first virtual call is at `0x58322`; its false branch begins at `0x5832a`. `commit_pte` is called at `0x5832f`; its false branch begins at `0x58336`.

This helper is not a simple `bool(map *)`: it receives the map and output pointers and returns separate control/output state. Routing it with a guessed Boolean ABI would be unsafe.

`IOAccelMemoryMap::commit_pte` at `0x52c84` can bypass the virtual commit for specific flag combinations. The retained `0xb13` has neither bit `0x40` nor the applicable special `0x20` bypass. Its ordinary path calls current map vslot `+0x170` at `0x52cb0`.

These are two distinct flag words. Candidate178 captured IOAccel map flags at `map+0x10`. X6000's commit method uses a separate status field at `map+0x138`.

## Actual video-backing dispatch

The relevant map was observed with map flag bit `0x10` set. X6000 `batchMemoryMapPrepare` at `0x6550` tests that bit at `0x65be` and takes the fallback branch at `0x660c`. This prioritizes the video-backed resource path, but the retained object/thread token does not establish probe PID or nonce identity.

The concrete X6000-created video backing resolves as follows:

1. `AMDAccelVidMemory`'s vtable is at X6000 `0x165af8`, with address point `0x165b08` written by its constructor at `0x3a612`.
2. Current vslot `+0x148` at table location `0x165c50` has an external relocation to framework `IOAccelVidMemory::prepare` at `0x5619c`.
3. That method tail-calls `IOAccelMemory::prepare` at framework `0x28d6`.
4. Base prepare checks backing flags `[memory+0xc]` bit 2. If the object is not already prepared, it calls current vslot `+0x1b0`.
5. The AMD table's vslot `+0x1b0` at `0x165cb8` relocates to framework `IOAccelVidMemory::wire` at `0x561c0`.
6. `wire` calls current vslot `+0x1e8` at framework `0x5621a` and propagates its Boolean result.
7. The AMD table's vslot `+0x1e8` at `0x165cf0` resolves to X6000 `AMDAccelVidMemory::allocPhysical` at `0x3aa76`.

This is a proven direct backing-allocation boundary for this subclass. It avoids the cold helper's nonstandard ABI and does not need another virtual invocation.

## `AMDAccelVidMemory::allocPhysical` ABI and fields

The exact symbol is:

```text
__ZN32AMDRadeonX6000_AMDAccelVidMemory13allocPhysicalEv
```

It is `bool(this)` under the x86-64 kernel ABI. Its first 17 complete bytes are:

```text
554889e54157415641554154534883ec18
```

They contain only stack/register setup and no RIP-relative operand. The full route guard must compare all 17 bytes before installing the wrapper.

The method begins by testing the first word at `this+0x118`; a nonzero value returns false. Otherwise it selects one of several hardware-memory allocation callbacks from the flags and auxiliary fields. Every callback writes through the address of `this+0x118`, and deallocation later passes that same embedded object to the backend. A false return can therefore have several native causes; it does not alone prove general-heap exhaustion.

The observer's field labels are limited to meanings established by exact callers/getters:

| Offset | Width | Defensible label |
|---:|---:|---|
| `+0x40` | 64 | `length`; returned by `IOAccelMemory::getLength` |
| `+0x110` | pointer | `owner`; hardware-memory/allocator backend selected during initialization and used for allocation/deallocation |
| `+0x118` | 64 | `element`; first word of the embedded allocation element and allocation output target |
| `+0x120` | 64 | `raw120`; allocation input whose higher-level meaning is not yet proven |
| `+0x128` | 32 | `flags`; low allocation flag word read throughout `allocPhysical` |

The broader allocation record also contains fields at `+0x12c` and `+0x130`. Capturing a 64-bit word at `+0x128` would merge unrelated values, so the observer must read exactly 32 bits there.

## Why candidate179's commit observer is superseded

The written candidate179 design attempted to correlate outer map preparation with `AMDAccelMemoryMap::commitIntoGPUPageTable`. Its route ABI was plausible, but its proposed conclusions were not concurrency- or retry-safe.

### Last commit is not the final attempt

The outer resource path can retry preparation after reclaiming other resources. An earlier attempt can enter commit and return false, while a later final attempt fails backing preparation before commit. The last observed commit inside an outer call is then not the final blocking branch. A commit-false record can prove that a commit rejection occurred; it cannot prove that commit caused the enclosing final failure.

### Reusable slot lifetime races

A scanner can observe an active same-map/thread slot, be preempted, and resume after the owner clears and reuses that slot for another call. Release/acquire publication of one `active` flag protects initial publication but does not preserve the slot generation across the scanner's reads. A token helps only if every read validates an unchanged atomic generation before using the fields. Nested same-map/thread calls add ambiguity even without reuse.

### Repeated counter snapshots are not coherent publication

A producer can pause between entry, exit, and result counter updates. A worker may read the same mixed vector twice while the producer remains paused. Two identical snapshots prove only that no counter changed between the reads; they do not prove that the accounting operation is complete. Treating this as malformed would reject legitimate in-flight callbacks.

### Zero route entries require dispatch coverage

Zero X6000 commit entries localizes failures upstream only if the exact dynamic dispatch to the routed override and the whole observation interval are proven. A global counter cannot attach an unrelated native commit to one outer call, map, process, or probe.

The direct `allocPhysical` observer avoids all four problems. It records one concrete synchronous call without cross-call matching, slot reuse, or composite entry/exit arithmetic.

## Approved observer contract

The implemented observation path is diagnostic-only and reuses `rgpusubmit=1`:

- Install the exact X6000 `0x3aa76` route only when its 17-byte entry guard matches.
- Include this sixth route in the all-routes-ready gate. A future experiment requiring `submission_backing_allocation` must reject a legacy five-route record and require the worker's initial zero-count summary before starting its workload.
- When capture is inactive, call the native target directly before computing a thread token, sequence, or field snapshot.
- When active, copy the five proven scalar fields, call native exactly once, copy the same fields again, append the completed result, and return the native Boolean unchanged.
- Keep independent successful and failed lifetime counters. A worker loads each once and derives `completed = successful + failed` from those two local values. This is explicitly a live snapshot, not an atomic final vector.
- Retain only the first four immutable failure observations. Continue the lifetime counters after saturation and report the sample drop count.
- Publish the initial readiness summary immediately. Publish dirty aggregate snapshots no more often than once per six seconds and cap them at 32; the 180-second worker can therefore expose continuous late activity without exhausting the budget. Failure samples remain available as soon as the worker observes their release-published slots.
- The callback performs no allocation, MMIO, logging, formatting, lock acquisition, wait, or extra native/virtual call.
- `current_thread()` is a kernel worker identity only. The record does not claim a map-to-PID, map-to-probe, or retry relationship.

The production helper is [BackingTrace.hpp](../../../src/BackingTrace.hpp), its concurrency and behavior fixture is [test_backing_trace.cpp](../../../tests/test_backing_trace.cpp), and the route/worker integration is in [RaphaelGPU.cpp](../../../src/RaphaelGPU.cpp).

Interpret results narrowly:

- A retained native false call proves that at least one concrete AMD video-backing physical allocation failed with the shown live inputs/state. It does not prove that this call belongs to the Metal probe or that allocator capacity is the cause.
- Native true calls prove that some physical allocations succeeded. They do not prove the target resource's superclass prepare or later PTE commit succeeded.
- Zero calls during an otherwise complete interval means this particular allocation boundary was not reached. It does not by itself prove commit failure because the backing may already be wired or may use another subclass/path.
- Outer failures plus repeated allocPhysical false results strengthen the backing-allocation hypothesis. A functional fix must still repair a proven violated ownership, range, or allocator contract rather than force false to true.

## Allocator and recovery corrections

`IOAccelMemoryAllocator2::init_pool(total, reserveStart, reserveLength)` at framework `0x1facc` initializes the pool from the first numeric argument, then calls `reserve(nullptr, reserveStart, reserveLength)`. The two-argument overload at `0x1f8e8` computes `total = start + length`, initializes that total, and reserves `[0,start)` by calling the three-argument form with `reserveStart=0` and `reserveLength=start`.

X6000 `AMDHWMemory::enableAllocations` at `0x52a1e` calls the two-argument overload. Its equal-size branch passes the same `(base,length)` form to both pools. The original 512 MiB total / 256 MiB visible values can therefore be intentional inputs to different native decisions. The disassembly does not show an inverted start/end interval, and swapping the fields is rejected.

The historical comparison remains material:

- Candidate171 used the full 256 MiB visible capacity, created client channel activity, and reached an SDMA paging submission, though it also logged 4 MiB allocation failures.
- Candidates175-178 applied a 240 MiB cap for recovery scratch. Candidates176-178 rejected the first Metal command before client submission.
- Candidate178-A/B produced 1,014 outer failures classified in the final backing/PTE phase, with no capacity-class or final-VA-class failures.

This is correlation across nonidentical builds, not isolated causal proof. Duplicate manual/native `enableAllocations` also occurs in both candidate171 and candidate178, so it is not the differentiating change even though unconditional pool reinitialization remains risky until its lifetime is proven safe.

The old fixed recovery descriptor/scratch placement has a separate ownership problem: it can overlap an earlier native top-down VMM reservation. Successful post-stop recovery does not prove exclusive ownership while macOS is running. Any functional replacement must first establish a native-owned lease and exclude that exact range from ordinary allocation. It must preserve the native allocator's intended capacity/visible semantics and cannot simply put scratch back inside Apple's live heap.

A later functional experiment should compare these stages independently:

1. native accelerator and engine startup;
2. client channel activity;
3. captured submission entry;
4. compute acceptance and checked readback;
5. render acceptance and checked pixels;
6. cleanup/recovery validation.

The raw historical verdict remains unchanged. A new comparison should report an observed stage regression only when the relevant capture is present; absence without sufficient capture is `unknown`.

## Review disposition

The safest next source change is the independently reviewed recovery-ownership repair, paired with the observation-only `allocPhysical` route. The observer can determine whether concrete video-backing allocation failures persist without adding a fragile cross-call correlation framework. The functional change must retain native results, preserve 256/256 allocator behavior initially, and exclude only a proven native-owned lease.

Metal acceptance remains the existing checked compute and render probe. A disappearance of `kIOReturnNoMemory`, successful allocation counters, or a reached `submitBuffer` is progress evidence, not acceptance by itself. Correct compute values, render pixels, desktop lifecycle, and presentation remain separate gates.
