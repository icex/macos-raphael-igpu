# The "KIQ blocker" is a graphics-ring hang on the first desktop draw

Date: 2026-09-13, after the host reboot to boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`.
Read-only audit of the run ledger under `/home/bogdan/macos-vm/run/`, the pinned Linux
sources, and the candidate-194 through candidate-209 source lines. No hardware action.

## Result

Every "KIQ" failure since candidate 194 is a misattribution. In the fresh-boot runs of the
same 1.0.194 binary (`metal-035-small-output`) and of candidate 204
(`candidate-204-retry-results`), the KIQ ring keeps completing its own stamps
(`waitForHwStamp(N) -> 1 caller=x6+0x5c75f`, `submitKIQFrame -> 1`, read pointer advancing
0x20, 0x40 ... 0x1c0). The waits that return 0 come from caller `x6+0x8f96b`, which
`re/x6000.asm:167578` places directly after
`AMDRadeonX6000_AMDGFX10HIQHWChannel::submitUnmapQueuesPacket()`: they are HIQ
UNMAP_QUEUES packets that never retire, and they fail only after the graphics ring has
stopped consuming.

| Run | Boot / launch | KIQ stamps | First failing wait | gfx ring at first KIQ observation after failure | GPU hang owner |
|---|---|---|---|---|---|
| `metal-028-194-resealed` (pass) | f828eb26, 2nd launch | 1..5 ok | none | `RPTR=0x80 WPTR=0x80`, `CP_STAT=0`, GRBM `0xa0003028` | `FirstPendingCB: PID = -1` |
| `metal-035-small-output` (same kext binary) | 1a97ba0a, 1st launch | 1..4 ok, later timeout | `waitForHwStamp(4) -> 0 caller=x6+0x8f96b` at line 2735, before the probe spawned at 2743 | `RPTR=0x2031 WPTR=0x2200`, `CP_STAT=0x94079200`, GRBM `0xe7f10028` | `WindowServer` VMID 2, `WallpaperSequoia` Metal VMID 3 |
| `candidate-204-retry-results` | 2f77212f, 1st launch | 1..4 ok, later timeout | `waitForHwStamp(4) -> 0 caller=x6+0x8f96b` at line 2699 | `RPTR=0x1eb1 WPTR=0x2100`, same status words | `WallpaperSequoia` Metal VMID 3 |
| `candidate-205..209` | 2f77212f, launches 5..11 | stamp 1 -> 0 immediately | n/a | `CP_STAT=0x94079200` already at RLC start | dirty GPU left by the run above; not evidence about the driver |

Decoded with `ref/linux/gc1036/asic_reg/gc_10_3_0_sh_mask.h`, the stalled state is a draw
that never reaches end-of-pipe, not a fetch or VM problem:

- `CP_STALLED_STAT2=0x230000`: `MEQ_TO_ME_NOT_RDY_TO_RCV`, `STQ_TO_ME_NOT_RDY_TO_RCV`,
  `QU_STALLED_ON_EOP_DONE_PULSE`; `CP_STALLED_STAT3=0x800`: `CE_WAITING_ON_CE_BUFFER_FLAG`.
- `CP_BUSY_STAT=0x448000`: `GFX_CONTEXT_BUSY`, `EOP_DONE_BUSY`, `CE_PARSING_PACKETS`.
- `GRBM_STATUS=0xe7f10028`: GE, SX, SPI, BCI, SC, PA, DB, CB busy, `GUI_ACTIVE`.
- `VM_FAULT_STATUS=0` while stalled; the single `0x40953` fault (VMID 0, write, walker and
  mapping error) appears only at teardown, thousands of lines later.

## What changed after the pass

The kext binary of `metal-035` is byte-identical to the pass (`7623059a...`). The manifests
differ in the guest boot disk, the probe program and harness scripts; the boot disk hash
changes on every run, so it is not a discriminator. The discriminator is the guest session:
the pass and candidate 193 never mention WindowServer and their console user stays
`lin 0`; every run from `metal-029-195b` onward logs `IOConsoleUsers ... lin 1` and an
Aqua session with `WindowServer` and `WallpaperSequoia` submitting Metal work to the
accelerator. The auto-login and virtual-display work recorded in
`2026-09-11-desktop-virtual-display.md` and `2026-09-11-temporary-autologin.md` was
written between the pass (05:48Z) and the first failure (13:08Z) that day. The recovery
receipts show the same boundary independent of boot: every run through the pass quiesced
`active_before=2 dequeued=2 dequeue_timeouts=0`; every run after it shows
`active_before=9 dequeued=1 dequeue_timeouts=8`. The eight unretired HQDs are the
compute queues whose UNMAP_QUEUES packets could not retire behind the hung graphics ring;
they are a symptom, not a cause.

The candidate-194 pass therefore proved compute plus a small offscreen render on an idle
graphics ring. It did not prove that the graphics pipeline survives a full desktop draw,
and no run has yet.

## Host state facts that bound the search

- At amdgpu unbind on this APU (APU, GC < 11) `amdgpu_device_fini_hw` performs a MODE2
  reset through the SMU (`nv_asic_mode2_reset` -> `GfxDeviceDriverReset(2)`); the journal
  of the last two GPU boots shows `MODE2 reset` after `finishing device.` with no failure.
  The first guest launch per boot starts from a PMFW-reset GC with CP and RLC halted and no
  CP firmware, which matches every fresh-launch `pre-TTL: BOOTLOAD=0 RLC_CNTL=0 MEC2 instr 0`.
- Between two guest launches on the same boot there is no reset of any kind: no FLR,
  `pm` reset is quirk-disabled for ATI VGA functions, the advertised `bus` method is refused
  at reset time because bus 7b carries five host-owned sibling functions, and vfio-pci and
  QEMU therefore skip reset on open, close and machine reset. Same-boot relaunch after a
  hang measures the previous run's wreckage.
- The dummy SMU back end means the guest never sends `DisallowGfxOff`, `AllowGfxOff`,
  `SetHardMinGfxClk` or `PrepareMp1ForUnload`; Linux sends all of them on this part. This
  did not stop the KIQ or the pass, but it remains untested for sustained graphics load.
- Linux applies a GC 10.3.6 golden table that Navi23 (10.3.4, the identity Apple sees) does
  not have: `GB_ADDR_CONFIG` mask `0x0c1807ff` value `0x42`, `CH_PIPE_STEER=0x44`,
  `GL1_PIPE_STEER=0x44`, `GL2_PIPE_STEER_0/1=0x32103210`, `GCR_GENERAL_CNTL` (Vangogh
  form), `UTCL1_CTRL=0x00100000`, `SQG_CONFIG=0x1000` (`ref/linux/gc1036/golden_settings_diff.txt`).
  Neither Apple's path nor the kext writes any of them; no run has ever read them back.

## Next step, in order

1. Reproduce the 194 conditions once on a fresh boot with auto-login off so the graphics
   ring stays idle; this confirms that the compute and offscreen path is still intact with
   the current source and separates guest-session drift from code drift.
2. In the same boot, before any desktop session, read and record `GB_ADDR_CONFIG`
   (`GC seg0 + 0x263e`), `CH_PIPE_STEER`, `GL1_PIPE_STEER`, `GL2_PIPE_STEER_0/1`,
   `UTCL1_CTRL`, `SQG_CONFIG`, and `GCR_GENERAL_CNTL`, and compare them with the Linux
   10.3.6 golden values. Also record `RLC_PG_CNTL`, `RLC_GPM_STAT` and `RLC_CP_SCHEDULERS`.
3. Only if step 2 shows the 10.3.4 values or reset defaults, add a one-time write of the
   10.3.6 golden set before RLC start, gated by a boot argument, and retest the desktop
   draw with `FirstPendingCB`, the gfx ring pointers and the CP stall words as the
   acceptance signals.
4. Stop iterating on KIQ dequeue and MEC-halt probes; candidates 205 through 209 measured
   a hung GPU and the mode-3 probe cannot succeed by construction (candidate 208 showed
   Apple's `_gc_create_kiq_queue_10_3` clears the halt bits as its first write).
5. Never relaunch on the same boot after a graphics hang: with no reset path, every such
   launch inherits the hang.

## Evidence pointers

- KIQ stamp callers: `/home/bogdan/macos-vm/run/metal-035-small-output/serial.txt:2038-2105,2555,2735-2762`;
  `/home/bogdan/macos-vm/run/candidate-204-retry-results/serial.txt:2080-2147,2531-2699`.
- Ring and stall words: `metal-035-small-output/serial.txt:2764`, `candidate-204-retry-results/serial.txt:2622-2628`.
- Hang owners: `metal-035-small-output/serial.txt:3355,3365`; `candidate-204-retry-results/serial.txt:3213`.
- Pass ring state: `/home/bogdan/macos-vm/run/metal-028-194-resealed/serial.txt:2162,2308`.
- Caller identity: `/home/bogdan/macos-vm/re/x6000.asm:167576-167580`.
- Golden tables: `/home/bogdan/macos-vm/ref/linux/gc1036/gfx_v10_0.c:3478,3589` and `golden_settings_diff.txt`.
- Host reset behaviour: kernel journal for boots `95ac6099` and `2f77212f` (`finishing device.` then `MODE2 reset`).

## Candidate 210 result (2026-09-13, boot `c369c74e`, run `ac4d2e151164b314892b4b4649bb8499`)

First launch on a fresh boot, boot arguments identical to candidate 194 plus nonces, no
`rgpumqdrestore`. Evidence: `/home/bogdan/macos-vm/run/candidate-210-attempt-golden1-results/`.
The graphics ring hung exactly as predicted (`HW Channel 0 GFX is occupied by channel 35
stamp 8`, `FirstPendingCB: WindowServer VMID 2` / `WallpaperSequoia Metal VMID 3`, first
failing wait `waitForHwStamp(4) -> 0 caller=x6+0x8f96b`, KIQ stamps fine until the late
`Stamp Timeout`), the probe timed out, recovery left eight HQDs unretired and shutdown was
forced. Verdict `BASELINE_BLOCKED/kiq` is the classifier's label, not the mechanism.

The read-only `XG:` samples were identical at pre-TTL, before/after RLC start and the first
KIQ submit:

| Register | Read | Linux 10.3.6 golden (mask) | Match |
|---|---|---|---|
| `GB_ADDR_CONFIG` | `0x42` | `0x42` (`0x0c1807ff`) | yes |
| `GL2_PIPE_STEER_0/1` | `0x32103210` | `0x32103210` (`0x77777777`) | yes |
| `CH_PIPE_STEER` | `0xe4` | `0x44` (`0xff`) | **no** (SoC default; the 10.3.3/10.3.7 value) |
| `GL1_PIPE_STEER` | `0xe4` | `0x44` (`0xff`) | **no** |
| `UTCL1_CTRL` | `0xa00000` | `0x00100000` (`0xffffffff`) | **no** (the Navi23 10.3.4 golden value Apple applies) |
| `GCR_GENERAL_CNTL` | `0xf00500` | `0x500` (`0x1ff1ffff`) | **no** |
| `SQG_CONFIG` | `0` | `0x1000` (`0x17ff`) | **no** |
| `RLC_CP_SCHEDULERS` | `0x58504840` | Linux writes byte 0 = `0xc8` for the KIQ | **no** (no valid bit; byte 0 names me2/pipe0) |
| `RLC_PG_CNTL` / `RLC_GPM_STAT` | `0` / `0xf40016` | PG off, GFX powered and clocked | fine |

`0xe4` steers four logical pipes to four physical ones; `0x44` folds them onto two. Raphael
has two DDR5 channels and one WGP, so the default routes part of every large working set to
channels and GL1 instances that do not exist. That is consistent with a full-screen draw
stalling the whole 3D pipe with no VM fault while small offscreen work completes.

Candidate 211 applies Linux's complete `golden_settings_gc_10_3_6[]` once before RLC start
behind `rgpugolden=1`, with per-register before/after/readback logging.

## MODE2 reset without reboot (2026-09-13)

`tools/smu-mode2-reset.py` (branch `candidate-209-review`) reproduces the host driver's
unbind reset through user-owned VFIO: it talks to the MP1 13.0.5 mailbox
(message SMN 0x03B10508, response 0x03B10984, argument 0x03B10988) through the NBIO 7.2
`PCIE_INDEX2/DATA2` pair at BAR5 offsets 0x38/0x3c. The probe found the mailbox still
holding the host's own `GfxDeviceDriverReset(2)` from unbind and `GetSmuVersion` returned
firmware 0x625300. The reset returned OK and took the hung GC from `CP_STAT=0x94079200`,
`GRBM_STATUS=0xe7f10028`, `RLC_CNTL=1` to `CP_STAT=0`, `GRBM_STATUS=0x3028`, `RLC_CNTL=0`,
`RLC_BOOTLOAD_STATUS=0`, `CP_MEC_CNTL=0x50000000`, memsize 0x200, no PCI config change.
The recovery receipt for the prior run stays immutable and `incomplete`, so the relaunch
used the explicit `--manual-reuse --ack-risk` override. Receipts: `run/mode2-probe-1.json`,
`run/mode2-reset-1.json`.

## Candidate 211 result (run `e6438b2889e8a4333089087997663f5e`)

All golden writes landed except the upper bits of `GCR_GENERAL_CNTL`; readbacks at post-TTL,
after RLC start and before KIQ submit confirm `CH_PIPE_STEER=0x44`, `GL1_PIPE_STEER=0x44`,
`UTCL1_CTRL=0x100000`, `SQG_CONFIG=0x1000`. The graphics ring still stalled on channel 35
stamp 8 (`RPTR=0x1e31 WPTR=0x2000`, `CP_STALLED_STAT2=0x230000`, `STAT3=0x800`,
`GRBM_STATUS=0xe7f10028`), so the golden table is not the cause. The small Metal compute
probe passed (`passed:true`, one completed command buffer) while the graphics ring was
stalled, which confirms compute and the KIQ/HIQ path are healthy and isolates the fault to
one graphics command buffer that never reaches end-of-pipe.

Next diagnostic (candidate 212): at the first ring stall, dump `CP_PFP_HEADER_DUMP`,
`CP_ME_HEADER_DUMP`, `CP_CE_HEADER_DUMP` (eight reads each), `CP_RB0_RPTR/WPTR`, the ring
dwords around the read pointer through the VMID 0 page-table walk, `CP_IB1/IB2_BASE/BUFSZ`,
`GRBM_STATUS_SE0`, `PA_SC_FIFO_SIZE` and `SPI_DEBUG_BUSY`, then decode the stuck PM4 packet
and, if it is a draw, the shader program address it references.
