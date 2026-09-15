# Source and assumption audit — 2026-09-15

## Conclusion

The claim that the DPG driver layer has zero discrepancies and that software
firmware loading is the only remaining lever is not supported. The native secure
clock-gate sequence differs from both native unsecure initialization and Linux.
Correcting it was observed at runtime, but did not produce encoded output.
The PSP authentication/decryption explanation remains a hypothesis.

This is a broad source and failure-path review, not a proof of all driver code
or a hardware qualification. Header arithmetic, fixtures and native disassembly
cannot establish MMIO accessibility, firmware execution, or desktop stability.

## Confirmed defects and corrections

| Area | Defect / assumption | Correction and evidence |
| --- | --- | --- |
| Secure VCN DPG | Native secure builder sends CGC_CTRL 0x104/0x105 to CGC_GATE (reg 1:0x88). | Candidate 254 substitutes zero at the exact native call site. Native unsecure and Linux use zero. Runtime log confirms 0x105 -> 0; encoding still stalls. |
| KIQ preparation | A partially latched MEC halt write returned failure without restoration or recording ownership. | Candidate 255 attempts restoration after the first write; retains held state if restoration cannot be confirmed. Partial-write/restore-failure fixtures pass. |
| SDMA layout | Inaccessible 0xffffffff source/destination reads could be merged into configuration writes. | Candidate 255 rejects inaccessible source and both destination registers, including watchdog sampling. Executed extracted production body with fault injection. |
| DPG prerequisites | Config could force secure DPG even if add_to_dpg_sram routing failed. | Candidate 255 requires that route before forcing config and refuses initialization if either config or SRAM route is missing. Executed initialization preflight with missing routes. This does not make all installation failures transactional. |
| Native ABI | wrapVmmFillRegs declared a 32-bit return for a Boolean native method. | Candidate 255 uses bool, matching native +0x6246c AL test and +0x6248f tail call. No claim that upper bits caused a recorded failure. |
| Hang decoding | parseWaitRegMem accepted opcode 0x93 with the seven-word 32-bit layout. | Candidate 255 rejects this unsupported form. AMD defines nine words with 64-bit reference/mask. Raw packet capture remains available. Malformed and real 64-bit packets are tested. |

The MEC and SDMA tests reproduced the original defects before their fixes.
Candidate 255 includes candidate 254's clock change, but has not run on hardware.

## Encoder investigation corrections

1. Native _engine_hw_init (+0x8757b) allocates ctx+0x340 SRAM in the mode-0 PSP
   branch. Mode 1 allocates software firmware but does not establish this SRAM
   allocation. Combining mode 1 with the secure initializer needs an allocation,
   ownership, address-domain and cleanup design; changing the selector alone is
   not the proposed clean experiment.
2. Linux indirect PSP loading also leaves firmware-cache BAR/size and stack BAR
   fields zero in this SRAM-building path. Those zeros alone do not establish an
   Apple-only signed firmware requirement or a decryption failure.
3. Native pause_dpg (+0x94cae) waits on POWER_STATUS (reg 1:4, expected 1/mask 3)
   before the pause acknowledgment (reg 1:0x14, expected 8/mask 8). The latter
   wait result is ignored before software pause state is updated. Generic
   cosWaitForFunc timeout text is insufficient to identify which stage failed.
4. Native secure initialization also differs from Linux in RB_ARB_CTRL unblock,
   REG_XX_MASK / RBC_XX_IB_REG_CHECK setup, and LMI_CTRL2 ordering/value.
   These are untested differences, not established causes. LMI_CTRL2 0x3e0000
   describes offload fields, not the stall bits.
5. submit_sram success, the firmware-loaded query and initialize returning zero
   are distinct observations. None independently demonstrates a VCPU instruction
   fetch, acknowledgment, or encoded frame.

Next discriminating observation: instrument the existing native register-wait
calls to record caller, bank/register, expected value, mask and return status.
_vcn_wait_on_reg_read is +0x86a3d; its millisecond variant is +0x86a9e. Verify ABI
and displaced instructions first. This distinguishes the power-state wait from
the ignored pause acknowledgment without adding speculative register writes.

## Candidate 254 hardware evidence

Run: 20736d213cddcb1d180d59795e3bd3a0.
Build: c781b5da6a7143dd98567f8ff107080c.
Boot: c369c74e-96ff-4c21-ae85-80ccb269f7d2.
Artifacts: /home/bogdan/macos-vm/run/candidate-254-results/.

- Function: harness desktop probe passed. Hardware H264 selected; first two
  frame submissions returned zero, third stalled; no callback/output captured.
  h264-hardware.jsonl is a pre-stop snapshot, not completed codec output.
- Identity/capture: run identity valid, secure CGC_GATE correction logged,
  five prior cache-window injections retained. serial.txt records subsequent
  timeout. Invalid/inaccessible register reads are not proof of firmware bytes.
- Cleanup: manual stop through harness; shutdown forced. recovery.json reports
  recovered with GC quiesced. host-after records VM stopped, vfio-pci retained,
  power pinned on. Prelaunch MODE2 receipt 107; no post-run MODE2 issued.
- Qualification: CORE_PROBE_PASS covers the probe. Encoder remains blocked;
  broad desktop stability and repeatable crash recovery are not established by
  this one run. The clock correction alone is insufficient.

## Broader source review and remaining assumptions

Reviewed non-generated src headers covering VCN, VM/page-table address domains,
SDMA topology, KIQ preparation, recovery reservations/lease/lifetime, engine
lifecycle, texture parsing, bounded diagnostics and submission/backing traces.
The generated VCN payload is checked through its existing manifest/hash tests,
not by interpreting every byte. Reviewed RaphaelGPU.cpp route installation and
boot-argument selection, firmware/PSP/SMU/VCN paths, active VM/SDMA/KIQ fixes,
BAR mapping, recovery ownership, power callbacks and texture COW integration;
sampled older experimental CP/MMIO surgery. This is not a line-by-line audit of
all historical disabled experiments, Python harness tools or external Lilu code.
The host suite and standalone fixtures provide additional regression coverage.

Remaining concerns, not fixed or claimed causal here:

- Many older fixed-offset routes lack whole-image identity and bounds checks.
  A matching short prologue does not authenticate an entire native build or all
  structure offsets. Harness identity must not be mistaken for per-route ABI
  validation; installation is not an atomic all-or-nothing transaction.
- Dummy SMU handlers bypass native behavior. A zero return does not implement
  platform power management. The targeted VCN power command is narrower than
  a complete Raphael SMU backend.
- SDMA watchdog MMIO and retained global hardware/BAR pointers still rely on
  object lifetime, power-state and concurrency assumptions. Rejecting sentinel
  reads does not close the race between a valid read and a later write.
- Texture COW validates exact UUID/bytes and attempts protection restoration;
  restoration can fail and is logged. Concurrent execution, mapping lifetime
  and the full protection lifecycle are not proven by the local parser tests.
- Older queue diagnostics write selectors; ucode diagnostics write index ports.
  They are not universally passive observations. Legacy dumpMecQueues restores
  selector zero rather than the previous selector, and experimental aperture/
  reset code contains historical machine-specific assumptions. Keep these out
  of causal claims unless their active boot flags and effects are accounted for.
- Historical comments about empty firmware, locked caches, MMHUB accessibility,
  or reset impossibility are investigation hypotheses, not current evidence.
  Register sentinel values and downstream queue timeouts cannot settle them.

No main merge/push. Original ~/src checkout and candidate-253 changes untouched.

## Source references

Native decompilation and instruction listings:
/home/bogdan/macos-vm/re/decompiled-24G830/HWLibs-full/functions/:
0x93fcf secure SRAM builder, 0x93d8e unsecure clock setup, 0x93f5d SRAM append,
0x943cf secure initialize, 0x8757b allocation, 0x94cae pause.
X6000-full/functions/: 0x62400 fillVMRegisters, 0x980c0 MMHUB implementation.

- [Linux VCN3 implementation](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/vcn_v3_0.c)
- [Linux PSP implementation (v6.12)](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_psp.c)
- [AMD PM4 definitions, PM4_ME_WAIT_REG_MEM64](https://github.com/GPUOpen-Drivers/pal/blob/dev/src/core/hw/gfxip/gfx9/chip/gfx9_plus_merged_f32_me_pm4_packets.h)

## Validation of candidate 255

- Host suite: 931 tests run, OK, 3 skipped. Log:
  /home/bogdan/macos-vm/run/candidate-255-host-tests.log.
- All 21 standalone C++ test fixtures compiled with -Wall -Wextra -Werror and
  executed successfully. This includes MEC partial-halt and wait-decoder cases.
- Kext build succeeded (existing compiler/deprecation and linker warnings).
  Log: /home/bogdan/macos-vm/run/candidate-255-build.log.
- Built source commit: c190572e74b6e1a01181cbfa7ce53b07df61f951 (clean).
  Build ID: c333c450275142d2b7ca0ec1f68d1c51.
  Archive: /home/bogdan/macos-vm/run/candidate-255-dist/RaphaelGPU-1.0.255-experimental.zip.
- No candidate-255 hardware execution. Final read-only host check: same boot,
  vfio-pci, power/control=on, no QEMU. No runtime correctness claim for 255.
