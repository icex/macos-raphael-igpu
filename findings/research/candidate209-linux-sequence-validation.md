# Candidate-209 Linux sequence validation

Date: 2026-09-13. The pinned local source is Linux stable v7.2.3
`gfx_v10_0.c` at
`/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-stable-v7.2.3/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c`, SHA-256
`39de93ff6255423855ad3434d415d867b55dc0c0c268410fba3950af9355a473`.
The adjacent CachyOS 7.2.3-2 cache has the same file hash. The separate
GC10.3.6 reference used for the cross-check is
`/home/bogdan/macos-vm/ref/linux/gc1036/gfx_v10_0.c`, SHA-256
`b8bf032fea2e6da3fc3517eed86fd395a2a764a6a3f63699fde4d6a16c06f100`.
The primary upstream reference is
[`gfx_v10_0.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c).

Linux uses `CP_MEC_CNTL_Sienna_Cichlid` at offset `0xf55`, base index 0
(current upstream lines 71–74). Its normal queue setup is
`gfx_v10_0_kiq_init_queue` -> `gfx_v10_0_kiq_init_register`
(`v7.2.3:7146–7177`). The caller selects the KIQ GRBM tuple, invokes
`amdgpu_ring_init_mqd`, then programs the queue and restores selector zero
under `srbm_mutex` (`v7.2.3:7178–7219`).

`gfx_v10_0_kiq_init_register` (`v7.2.3:7037–7130`; GC10.3.6 reference:
`6885–6993`) disables WPTR polling, requests dequeue only if ACTIVE, and waits
up to `usec_timeout`. The loop has no error check after timeout, so Linux
intends to reach an inactive queue but does not guarantee ACTIVE became zero
before continuing. It then writes the MQD dequeue value, RPTR and WPTR. It disables the HQD doorbell before writing
EOP base low/high and EOP control, then writes MQD base/control, PQ base/control,
RPTR report and poll addresses, enables the MEC doorbell range if requested,
restores HQD doorbell control, writes WPTR again, VMID/persistent state, and
finally ACTIVE. Linux therefore programs the complete HQD/EOP image under the
intended inactive state; it does not require a running queue to accept EOP
writes.

Linux’s explicit MEC enable/disable helper is separate:
`gfx_v10_0_cp_compute_enable` (`v7.2.3:6612–6651`) writes zero to enable and
the ME1|ME2 halt mask to disable, followed by 50us delay. Firmware loading
calls disable before MEC microcode work (`6666`); KCQ resume calls enable before
KCQ setup (`7224–7229`). KIQ resume itself calls `gfx_v10_0_kiq_init_queue`
(`7214–7217`) and does not toggle MEC there. Linux source provides no evidence
that KIQ init’s HQD writer
unhalts MEC as part of the queue sequence.

The EOP register fields are the ordinary `mmCP_HQD_EOP_BASE_ADDR`, `_HI`, and
`_CONTROL` entries (`v7.2.3:398–403`; current upstream source uses the same
names). EOP control is written before MQD/PQ and before ACTIVE. Doorbell range
and HQD doorbell control are enabled only after those image writes. Ring command
publication is later software activity; Linux’s KIQ ring uses a MEC doorbell
index (`v7.2.3:4695–4702`) and writes doorbell WPTR only after commands are
written.

## Comparison and limits

Candidate-209’s scoped transaction closes queue-local ingress, saves MEC
control, halts both MECs, clears/reads back HQD state, calls native, and on the
mode-3 probe path always writes `savedMEC | 0x50000000` and returns failure;
it does not restore a saved running MEC state or claim an intentional unhalt.
This is an experiment containment boundary, not a production recovery path.
Apple’s native HWLibs `_gc_create_kiq_queue_10_3` clears MEC halt bits at
`hwlibs.asm:0x1501e–0x1506e` before later HQD/EOP programming, whereas Linux
keeps MEC enable/disable outside the KIQ queue writer. The Linux ordering
supports testing this boundary, but does not endorse invoking Apple’s native
writer with MEC halted or prove the resulting state recoverable.

Linux validates the ordering described above and the named register mapping;
the complete bit-level encoding equivalence to Apple’s image remains unproven.
Linux’s PSP/RLC resume path (`gfx_v10_0_cp_resume`, v7.2.3:7236–7265;
GC10.3.6 reference: 7115–7142) calls `kiq_resume` before `kcq_resume`; the
shown `cp_compute_enable(true)` belongs to KCQ resume (v7.2.3:7220–7229;
GC10.3.6: 7086–7100), while KIQ resume is at v7.2.3:7214–7217
(GC10.3.6: 7062–7081). PSP/RLC startup therefore does not establish that MEC
is halted at KIQ entry. Apple’s RLC/TTL indirection and command-8 behavior
remain outside Linux’s proof.

The public Apple reference available for the framework boundary is
[`IOFramebuffer.h`](https://github.com/apple-oss-distributions/IOGraphics/blob/main/IOGraphicsFamily/IOKit/graphics/IOFramebuffer.h).
It describes the public IOGraphics/IOFramebuffer interface only; it does not
specify the proprietary AMD HWLibs queue writer or its CP_MEC_CNTL behavior.

## Candidate-209’s exact native guard

The active candidate-207 source used for candidate-209 has a narrow guard in
`src/KiqQueuePreparation.hpp:23–30`. `preserveNativeMecHalt` admits only
`mode==3`, `mqdMode==2`, the atomic probe-armed flag, native caller offset
`0x15073`, register `0x21b5`, client `0xb`, flag `1`, and a matching GC
context. `wrapGcCgsWrite2` (`src/RaphaelGPU.cpp:1891–1926`) applies it before
forwarding the original write by ORing `0x50000000` into the requested MEC
value. The mode-3 failure path separately writes the halt mask and returns
failure. This is a contained call-site experiment; it does not claim all
CP_MEC callers are safe or restore a saved running-MEC state.
