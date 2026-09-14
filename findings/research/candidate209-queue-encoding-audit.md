# Candidate-209 queue encoding audit

This is a read-only comparison of the candidate-209 queue preparation code with the
local GFX10 Linux reference. No source, hardware state, or run artifact was changed.

## EOP

The Linux reference defines `GFX10_MEC_HPD_SIZE` as 2048 bytes and, in
`gfx_v10_0_compute_mqd_init()` (`/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-cachyos-7.2.3-2/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c:6931-6940`), computes
`EOP_SIZE = order_base_2(size / 4) - 1`, yielding control value 8 for that allocation.
It also encodes the base as `eop_gpu_addr >> 8` and splits the shifted value into low
and high words. Candidate-209 uses the same base encoding in
`src/KiqQueuePreparation.hpp:193-202` and `:56-57`.

The value 6 observed in Apple's queue is not by itself an encoding error. Root's
disassembly review of the Apple HWLibs path at `0x152f9..0x15312` shows the same
size-to-log2-minus-one calculation. The observed control 6 is consistent with a
512-byte size supplied to that path, but the descriptor size was not directly
measured. Therefore Linux's value 8 and Apple's value 6 may describe different EOP
allocation sizes.

Candidate-209's strict `eopControl == 6` checks in
`haltedNativeResultVerified()` and `programEopForNativeStart()` can still produce a
false negative if Apple preserves other control bits or uses another valid size. The
current runtime evidence supports control 6 for this Apple allocation, but does not
justify a blind change to 8 or a claim that the whole control word is universally 6.

## MQD and PQ

The Linux `v10_compute_mqd` layout (`ref/linux/gc1036/v10_structs.h:804-843`) places
the MQD pointer at image offsets `0x200/0x204`, PQ base at `0x220/0x224`, and EOP
base/control at `0x294/0x298/0x29c`. Linux writes MQD addresses directly but writes
the PQ base as `hqd_base_gpu_addr >> 8` (`gfx_v10_0.c:6967-6979`). Candidate-209
reads the PQ words from `0x220/0x224` and compares them directly in
`RaphaelGPU.cpp:4261-4262` and `KiqQueuePreparation.hpp:53-57`; those are already
the encoded MQD image fields, so no extra shift discrepancy was found.

## Selector

The Linux masks in `gc_10_3_0_sh_mask.h:6182-6189` are PIPEID shift 0, MEID shift 2,
VMID shift 4, and QUEUEID shift 8. `nv_grbm_select()` writes those fields directly
(`ref/linux/gc1036/nv.c:317-327`). Candidate-209's `kKiqSelector` is
`1 | (2 << 2) = 9`, representing pipe 1, ME 2, queue 0; this matches the validated
spec tuple in `RaphaelGPU.cpp:4146-4150`.

## Scope of the MEC guard

The 209 guard is scoped by `preserveNativeMecHalt()` in
`src/KiqQueuePreparation.hpp:23-30` and the corresponding `wrapKiqStart`/write path:
mode 3, MQD mode 2, an atomically armed transaction, caller `+0x15073`, register
`0x21b5`, client `0xb`, flag 1, and matching context. Modes 0/1/2 and unrelated
writes therefore retain their existing forwarding behavior. No evidence from this
audit proves a broader queue encoding issue; if EOP remains zero in a future 209 run,
the useful next evidence is the selected queue, actual native EOP writes/readbacks,
and expected values under the same boot.
