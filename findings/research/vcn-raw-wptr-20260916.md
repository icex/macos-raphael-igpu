# Decoder write-pointer protocol experiment

272 removes early PM rejection and creates a hardware decoder, then first decode
blocks on VCN0Dec stamp1. No decoded output. Cleanup forced/recovered.

Exact HWLibs24G830 queue_decode_3_0_submit_frame95650 copies one native queue slot,
advances native index, converts slot index to DWORD write pointer. In DPG mode,
956b7 ORs0x80000000 into ECX and stores it to shared+34 and SCRATCH2(7e16), then
writes the raw pointer to RBC_RB_WPTR(80e1) or the native doorbell.

Linux baseline source vcn_v3_0.c1828ff writes raw low32 wptr to all three. Actual
working capture linux-vcn-c782d007-active/register-trace.txt at3971.422347 onward
shows7e16 values70,90,b0,110, with no highbit. This is an observed protocol
difference; whether firmware ignores the highbit or interprets it is unknown.

273 changes the exact OR immediate to0, preserving instructions/control flow,
native queue ownership/allocation, memmove, index advance and commit order. Guard
requires original17-byte prologue and12-byte MOV/OR/store sequence. Enabled only
with explicit rgpuvcnwptr1 and no-DPM, Raphael firmware/APU, SMU and DPG options.
First four submissions log first64DWORDs and immediate pointer/MMIO readbacks;
no additional queue commands, waits or allocations. Live guards/readbacks must
confirm delivery. Queue reads are immediate observations, not completion proof.

Success requires actual hardware decoded callbacks and pixels. Confirmed raw
shared/SCRATCH2 pointer with continued stall falsifies this as sufficient fix.
Compare address translation and first packet next. Do not attribute shared/cache
read sentinels to a dead VCPU.

## Candidate275 offline verification (2026-09-16, after the273 host crash)

Linux history of the SCRATCH2 write pointer, checked against gregkh/linux tags:

| Driver | Kernel | `mmUVD_SCRATCH2` value in `dec_ring_set_wptr` |
|---|---|---|
| vcn_v2_0 (Renoir APU, DPG) | v7.2.5 | `lower_32_bits(wptr) \| 0x80000000` |
| vcn_v3_0 | v5.10, v6.1, v7.2.5 | `lower_32_bits(wptr)` (no high bit) |

VCN 3.0 DPG never used the high bit in any released kernel; Apple's
`_queue_decode_3_0_submit_frame` sets it only inside the `flags & 2` (DPG) branch,
which no shipping Apple product exercises (no APU). The273 patch therefore removes
a VCN 2.x-era protocol difference rather than a guess. It remains unqualified on
hardware because273 lost host capture before its first submission.

Doorbell routing, checked offline so275 need not test it blind:

- `_IpiBgmSetSwipDoorbellApertureRange` maps HW block0xc (VCN) to doorbell type5
  and doubles the64-bit indices from `_AssignVcnDoorbellOffset` (0xf8..0xfb) to
  DWORD offset0x1f0, size8.
- `_nbio7_2_set_doorbell_aperture_range` writes `(size & 0x1f) << 16 | (offset & 0x3ff) << 2`
  = 0x807c0 to RSMU byte address0x1403bcc = (0x10400 + 0x4f0af3) * 4, i.e. Linux
  `regGDC0_BIF_VCN0_DOORBELL_RANGE` (BASE_IDX3 = 0x10400) through `amdgpu_device_pcie_port_wreg`
  (`reg * 4`). Field layout matches nbio_7_2_0_sh_mask.h (OFFSET shift2, SIZE shift16).
- `_queue_get_doorbell_address` rings `ttlDevGetDoorbellBase + 0x7c0` = DWORD index0x1f0,
  the same index Linux `WDOORBELL32(0x1f0)` uses for `vcn_dec_0`.
- 272 already logged `nbio7_2_enable_doorbell_aperture(enable=1)` with
  `BIF_DOORBELL_APER_EN=1` read back.

So Apple's decode doorbell programming is byte-for-byte what Linux does on this
silicon. 275 adds a read-only log of the range request/result and, after each of
the first four submissions, reads back RBC_RB_RPTR/WPTR, SCRATCH2, POWER_STATUS,
DPG_PAUSE and RBC_RB_CNTL (all AON/RBC registers 272 already read without incident)
plus the doorbell page offset. A raw write pointer with WPTR still0 after the
doorbell isolates a routing problem; WPTR advanced with no decode callback
isolates a firmware/packet problem. No LMI-domain, cache-BAR or LMA reads.

## Candidate275 hardware result (run 5cb7876d841a17cec484c12398fdf135)

Guard/patch/route 1/1/1. Doorbell range request logged: type 5, offset 0x310, size 8,
result 0 (Apple assigns VCN doorbells at 0x310 on this configuration; the ring's
doorbell page offset 0xc40 matches). Four decoder submissions: wptr 0x40/0x80/0xc0/0x100
with SCRATCH2 and shared wptr identical and rptr advancing 0 → 0xc0, power 0x905/0x906,
pause 0. H.264 hardware decode of a software stream, H.264 and HEVC hardware encode
with hardware decode all pass 3/3 frames (max luma error 1/1/0). HEVC hardware decode
of the software hevc.vcp stream fails at decoder creation (−12913) with no kernel
context; that is a userspace/format issue to investigate separately. The raw write
pointer hypothesis is confirmed sufficient on this baseline.
