# Historical bring-up notes

These notes preserve earlier hypotheses and experiments, including superseded claims.
Use the root README and dated findings corrections for current status.

### GC and SDMA HW_INIT: three gates upstream does not have

`TTL::initialize()` used to succeed only sometimes. On a host that had been running guests all
night it completed; after a host reboot — i.e. on a GPU that amdgpu had just MODE2-reset on
unbind, and vfio-pci reset again on open — it failed with `ttl_hw_init failed`. Reading the
timed-out `cosWaitForFunc` callbacks against the HWLibs symbol table named all three:

- `_gc_fw_autoload_is_completed` — requires `RLC_STAT == 0x25` **and** `BOOTLOAD_COMPLETE` in
  `RLC_RLCS_BOOTLOAD_STATUS`. Upstream's `gfx_v10_0_wait_for_rlc_autoload_complete` asks for
  `BOOTLOAD_COMPLETE` and `CP_STAT == 0`; the `RLC_STAT` clause is Apple's own, and it is a
  liveness sample rather than a latch. Measured here: `RLC_STAT` **is** `0x25`, and
  `BOOTLOAD_COMPLETE` is clear at *both* offsets — 0x4e8d, which Apple reads, and 0x4e7e, the
  one upstream defines as `mmRLC_RLCS_BOOTLOAD_STATUS_Sienna_Cichlid` and uses for every GC
  10.3.x including 10.3.6. Measured, both read 0 during GC HW_INIT and 0x4e8d reads
  `0xc0000001` *after* it, so on this part Apple's offset is the live one -- the latch is
  simply set by the RLC's backdoor-autoload bootloader, and when the PSP places the
  firmware itself nothing sets it until GC HW_INIT has already run. Reading the microengines' instruction RAM back
  through `CP_{PFP,ME,CE,MEC_ME1,MEC_ME2}_UCODE_ADDR/DATA` shows real instruction words in all
  five, so the microcode *is* there — `GFX_CMD_ID_AUTOLOAD_RLC` returning `0xffff000d`
  (`TEE_ERROR_BUSY`) is not the problem it looks like.
- `_sdma_5_2_fw_autoload_is_completed` — eleven instructions, and all of them read that same
  latch through the SDMA client. Upstream's `sdma_v5_2_start` has no such wait at all on the PSP
  load path.
- `_gc_enter_rlc_safe_mode_10_3` — writes `RLC_SAFE_MODE = CMD|MESSAGE` and waits 500 ms for the
  RLC to clear `CMD`. It never does. Upstream's `gfx_v10_0_set_safe_mode` returns `void` and
  simply proceeds after its timeout.

A fourth, in `_gc_create_kiq_queue_10_3`, is a faithful copy of upstream's
`gfx_v10_0_kiq_init_register` — deactivate a live HQD with `CP_HQD_DEQUEUE_REQUEST` and wait for
`CP_HQD_ACTIVE` to fall — except that upstream carries an explicit fallback Apple dropped:

```c
if (j == adev->usec_timeout) {
        DRM_DEBUG("KIQ dequeue request failed.\n");
        /* Manual disable if dequeue request times out */
        WREG32_SOC15(GC, 0, mmCP_HQD_ACTIVE, 0);
}
```

So milestone `xl` answers each of these the way upstream behaves, and only these: the predicate
filter is `(CP_HQD_ACTIVE | RLC_SAFE_MODE, mask 1, shift 0, expect 0)`, so the same helper's
other callers keep timing out honestly, and the autoload answer is conditional on `RLC_STAT`
still reading `0x25` — a genuinely dead RLC still fails here rather than three blocks later with
no explanation. With them in place `TTL::initialize()` completes and the accelerator registers on
a cold GPU, every time; and `RLC_RLCS_BOOTLOAD_STATUS` reads `0xc0000001` **afterwards**, which
is what made the original failure look like a race: GC HW_INIT is itself what sets the latch its
own gate was waiting for.

Negative result worth recording: an early `GRBM_SOFT_RESET` pulse of `SOFT_RESET_CP|SOFT_RESET_GFX`
before `TTL::initialize()` makes things strictly worse. `GRBM_STATUS` goes from `0x3028` (idle) to
`0xa0003028` and stays there, and GC HW_INIT then times out. Upstream only pulses that register
from inside RLC safe mode with the CP halted and re-initialised afterwards. The premise was wrong
too: on a freshly booted host the pre-TTL MEC walk reports *no* active compute queue, so the HQDs
seen later are not amdgpu's leftovers — they are Apple's own KIQ, and the eight "queues" are one
physical HQD seen through eight `GRBM_GFX_CNTL` selector aliases (identical MQD address in all
eight).

**PSP HW_INIT now completes.** Every IP firmware blob loads with status 0 — the whole RLC
family and all the CP microcode — and the PSP goes on to `EVENT__HW_UNINIT`.

The unlock was not the RLC firmware, which turned out to be a red herring: substituting this
chip's own signed RLC changed nothing. Reading the *per-command PSP response status* showed one
root failure with everything else a consequence — `LOAD_TOC` was rejected, so `tmr_size` came
back 0, so `SETUP_TMR` was handed size 0, so there was no TMR and the loads that need one
failed. HWLibs holds two 0x600-byte `$PS1` TOC containers and `_TOC_TABLE`'s `$PS1` FW ID is
**zero**, while `0x8000030a` decodes (from PSP `sys_drv` images embedded in HWLibs itself) as
*"unrecognised firmware type"*. Replacing both with the payload of this chip's own
`psp_13_0_5_toc.bin` — same 0x600 size, same signing key, fw_type `0x0101200e` vs Apple's
`0x0000200e` — makes `LOAD_TOC` return `tmr_size = 0xa00000`, the same value the host kernel
reserves for itself.

The remaining rejection is the tap-delay firmware, and it is *supposed* to be rejected:
`gc_10_3_6_rlc.bin` is header v2_2, so this chip has no tap-delay payloads, and upstream only
loads them when a v2_4 header declares them.

**`TTL::initialize()` now completes and the Metal accelerator attaches.** SMU HW_INIT fell
without porting any SMU-13 code, because the question turned out to be the wrong one. Apple's
`smu_11_0_7` drives the Navi 2x mailbox — register indices `0x282`/`0x292`/`0x29a`, i.e.
`MP1_SMN_C2PMSG_66/82/90`, named in the clear by `smu_11_0_7_send_message`. This silicon puts
its SMU mailbox at `MP1_C2PMSG_2/33/34`, SMN `0x3b10508`/`0x3b10984`/`0x3b10988` — the Zen SMU
aperture, not the GPU's MMIO window. So every message times out.

Retargeting those registers is mechanically possible and is still the wrong move: on an APU the
SMU is the *platform's* power controller, governing the CPU cores of the host this VM runs on,
brought up by the x86 firmware long before macOS exists. Apple already has a name for a GPU
whose power management belongs to somebody else — `PP_PhmUseDummyBackEnd`, one of 36 settings
in `_smu_config_name_mapping` — and it swaps hw_init, dpm, thermal, fan, power, ulv and gfx_off
for `dummy_smu_*` stubs that return 0. Milestone `xf` takes that path and clears the one
hardware call it leaves behind (`[smu+0x798]`).

What comes back is real hardware: `SE=1, SA/SE=1, numActiveCU=2, numActiveRB=1` is this iGPU's
actual topology, read out of the graphics core after it initialised.

The wall is now the framebuffer aperture. GPUCAP reports `FB: 512 MB` but
`FB Base: 0x100000000, Top: 0x100000000` — a zero-wide range — so the VRAM allocator has
nothing, and WindowServer's first command buffer page-faults in
`AMDAccelResource::BatchPrepareMappings`. Those values come from the MC/GMC framebuffer-location
registers, which live in MMHUB, and MMHUB 2.4.1 is currently being reported as 2.3.0.

Iteration is ~90 s end to end and needs no root: `preflight.py` validates every routed offset,
route safety, patch pattern and the embedded-firmware bytes against the KDK in under a second,
without booting.


