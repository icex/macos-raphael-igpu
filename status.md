# Live status — 2026-09-16, candidate 275: hardware video encode and decode work

## Current host and task boundary

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, Raphael `0000:7b:00.0` on **vfio-pci**,
`power/control=on`, no QEMU. Two VM exposures on this boot (274, 275); both ended
with `exited-after-guest-request` and a `recovered` receipt with no kernel messages.
Another run on this boot needs a new allowance note here plus MODE2 reset (next #135)
and `--manual-reuse --ack-risk`. No vfio-pci → amdgpu rebinding within a boot. Keep PCI
reset methods disabled. Nothing merged or pushed to main.

## Candidate275 — hardware codec milestone

Branch `candidate-275-vcn-wptr`, worktree `/home/bogdan/macos-vm/run/worktrees/candidate-275`,
kext 1.0.275, card `metal-122`, source `50fc83c`, run `5cb7876d841a17cec484c12398fdf135`,
build `39ee63ee96744007acbaf658fc254ccd`, MODE2 reset 134. Verdict **CORE_PROBE_PASS**
(offscreen Metal 1,000 frames, 24 readback cases). Artifacts
`/home/bogdan/macos-vm/run/candidate-275-results/`.

275 = 274's diagnostic-free source + 273's exact HWLibs OR-immediate patch at
`_queue_decode_3_0_submit_frame`+0x64 (`OR ECX,0x80000000` → `OR ECX,0`), so the shared
`rb.wptr` and `SCRATCH2` carry the raw DWORD write pointer as every released Linux
`vcn_v3_0` does. Apple only sets bit 31 in its DPG branch, which no shipping Apple
product runs. Guard/patch/route all reported 1. Read-only observers added: NBIO 7.2
doorbell range request (VCN type 5 → offset 0x310, size 8, result 0) and per-submission
AON/RBC readbacks.

Interactive-hold workloads (`tools/guest-codec-control.py`, 1280×720, 3 frames,
registry 4294968063), all with normal exit and no ring restart:

| Workload | Result |
|---|---|
| H.264 sw encode → **HW decode** (`decode-control-hw-h264-output.txt`) | 3/3 frames, 2,675,475 luma values, max error 1 — first hardware decode |
| H.264 **HW encode** (h264.gva) → HW decode (`video-codec-probe-hw-h264-*`) | 3/3, max error 1, 248/320/328 bytes |
| HEVC **HW encode** (hevc.gva) → HW decode (`video-codec-probe-hw-hevc-*`) | 3/3, max error 0 |
| HEVC sw encode (hevc.vcp) → HW decode (`decode-control-hw-hevc-*`) | decoder creation −12913, no kernel context; open |

Kernel evidence (serial `VCNQ`): four submissions, `wptr=40/80/c0/100`, `scratch2` equal,
`rptr` advancing to `c0`, doorbell page offset `0xc40` (= index 0x310 × 4, matching the
programmed range), power 905/906, pause 0. The earlier "VCPU never boots / wall below
the driver" conclusion is retracted: cache-BAR/soft-reset `0xffffffff` reads are normal
on working Linux as well.

## Open issues

1. HEVC hardware decode of a software-encoded (hevc.vcp) stream fails at
   `VTDecompressionSessionCreate` (−12913) before any kernel VCN context; the same
   decoder accepts the hardware-encoded HEVC stream. Userspace/format-description
   investigation, not a ring issue.
2. Only three-frame workloads are qualified. Sustained streams, other resolutions,
   HEVC Main10, alpha, and concurrent sessions are untested.
3. Full desktop/display path (DCN 3.1.5) remains unqualified; managed-texture copy
   limitation unchanged.
4. GPU handoff client guard (`fix/gpu-handoff-clients`, worktree `gpu-handoff-clients`):
   fixture-tested, not installed into `~/macos-vm/` copies or `experiment.py` harness
   list, not hardware-tested. Needed before any future amdgpu → VFIO handoff.

## Suggested continuation

1. HEVC sw-stream decode: compare the hevc.vcp and hevc.gva format descriptions
   (hvcC, chroma/profile) in the guest; likely a VideoToolbox capability mismatch.
2. Longer codec qualification (e.g. 600-frame H.264/HEVC like the Linux baseline)
   under one hold, then consider merging the 275 kext changes toward `dev`.
3. Finish the handoff guard before the next reboot-based Linux control.

Previous state archived in
`findings/research/status-archives/status-before-candidate275-result-20260916.md`.

## Next authorized run: 275 attempt hevc1 (HEVC software-stream decode investigation)

Extend allowance 2→3 on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed` under the user's
request to fix the HEVC software-stream hardware decode failure (−12913, 2026-09-16).
Same 1.0.275 kext and card metal-122 as run 5cb7876d (exited after guest request,
recovered receipt); isolated attempt namespace `hevc1`. Workload during the hold:
`tests/video_hevc_format_probe.m` via `tools/guest-codec-control.py` — dumps the hvcC
records of the hevc.vcp and hevc.gva streams, tries the software stream with
require-hardware, enable-only, software, and a parameter-set-only rebuilt format
description, then a fresh-process decode of the saved stream, and captures the guest
unified log for GVA/VideoToolbox messages. Read-only observation; no kext change.
Fresh MODE2, all identity/capture/host-fault/cleanup gates, max 6000 s. No amdgpu
rebind, merge or push. Stop through the normal harness.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-275-attempt-hevc1-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

## Next authorized run: 275 attempt hevc2 (clean HEVC decode ordering replication)

Extend allowance 3→4 on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, continuing the
HEVC decode investigation the user requested. Attempt hevc1 established that HEVC
hardware decode fails in AppleGVA userspace ("IOGVACodec not set" / −12913; −12906
with a registry id) even after a successful H.264 decode, while run 5cb7876d decoded
HEVC in hardware after H.264 decodes ran first from a clean boot. hevc1's boot was
contaminated by failed HEVC attempts, so it cannot test clean ordering. hevc2 runs
`tests/video_hevc_sequence_probe.m` once: in a single process on a fresh boot it does
H.264 sw→hw decode, H.264 hw→hw decode, then HEVC hw→hw decode (the 5cb7876d order),
plus a registry-scoped HEVC variant. Read-only; no kext change; same 1.0.275 kext and
card metal-122. Fresh MODE2, all safety gates, max 6000 s. No amdgpu rebind, merge or
push. Stop through the normal harness.
