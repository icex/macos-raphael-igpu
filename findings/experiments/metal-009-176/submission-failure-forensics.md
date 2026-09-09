# Candidate 176 first-submission forensics

The probe reached `commit`, completed asynchronously in about 194 ms, and returned
Metal command-buffer status 5 with `0xe00002bd`. The matching 24G830
`IOReturn.h` defines that value as `kIOReturnNoMemory`. Device discovery, shader
compilation, pipeline/queue creation, both managed buffers, encoders, dispatch and
commit therefore completed before the rejection surfaced. No command buffer
completed, no workload VMID-2 program or SDMA-submit callback was observed, and the
serial log contains no AMD GPU fault, reset, panic or hang. This locates the earliest
observed rejection at the asynchronous Metal completion boundary; it does not yet
identify the kernel branch that produced the return code.

The exact accelerator binary was
`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`
(SHA-256 `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`).
Its five bounded diagnostic routes have these verified x86-64 ABIs and complete,
non-RIP-relative entry spans:

| Offset | Symbol | ABI | Entry bytes |
|---:|---|---|---|
| `0x9ca6` | `AMDAccelCommandQueue::processCommandBuffer` | `void(queue *, uint32_t, uint32_t)` | 17: `554889e5415741564154534189d64189f7` |
| `0x18256` | `AMDAccelResource::BatchPrepareMappings` | `uint32_t(accelerator *, resource *const *, uint32_t)` | 17: `554889e54157415641554154534883ec18` |
| `0x184d8` | `AMDAccelResource::BatchPrepare` | `bool(accelerator *, resource *const *, uint32_t)` | 17: `554889e54157415641554154534883ec68` |
| `0x6550` | `AMDGraphicsAccelerator::batchMemoryMapPrepare` | `bool(accelerator *, IOAccelMemoryMap *)` | 16: `554889e54157415653504889f34989fe` |
| `0xb83e` | `AMDAccelChannel::submitBuffer` | `void(channel *, IOAccelCommandDescriptor *)` | 20: `554889e54157415641554154534881ec08010000` |

`setSubmissionError` at `0xace4` is deliberately excluded: its first RIP-relative
load begins at byte 12, and the X6000 text has no direct call to route safely.

The allocator implementation was extracted without mounting the local
`/home/bogdan/macos-vm/kdk/KDK-24G830.dmg`
(SHA-256 `9e2bb18ed726b805ffc009db30bc4bfe7539ed138746165600b0fd5a77562ed4`).
The archive member
`System/Library/Extensions/IOAcceleratorFamily2.kext/Contents/MacOS/IOAcceleratorFamily2`
has SHA-256 `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35`.
In that binary, `IOAccelMemoryAllocator2::init_pool(uint64_t,uint64_t)` at
`0x1f8e8` calls `init_pool(uint64_t)` at `0x1f784`, which clears allocator fields
and rebuilds its lists. Candidate 176 calls `AMDHWMemory::enableAllocations` twice
on the same pool objects, so the second call reinitializes their bookkeeping.
There is no evidence of a live allocation between those calls and no observed
allocation-failure log, so this is a hypothesis rather than an attributed cause.

Candidate 177 should run the unchanged probe with `rgpusubmit=1`. Before the probe,
the classifier must observe the exact five-route record and the worker's initial
summary. The trace then distinguishes queue processing, partial mapping preparation,
the final `BatchPrepare` result, individual map rejection, and whether `submitBuffer`
is entered and returns. It performs no MMIO, allocation, formatting, logging or waits
inside the routed callbacks.

The current evidence does not prove physical memory exhaustion, heap corruption,
GPU execution, a GPU VM fault, an SDMA failure, or a missing-callback logging bug.
