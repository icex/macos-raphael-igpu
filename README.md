# macOS on an AMD Raphael iGPU

Reverse-engineering notes and tooling for making Apple's Navi 2x graphics stack bind to the
**integrated GPU of a Ryzen 9000-series (Raphael / Granite Ridge) desktop CPU**, passed through
with VFIO to a macOS Sequoia guest under QEMU/KVM.

No Mac hardware, no macOS build host: everything here is produced and driven from Linux.

## Status

TTL's SWIP clients initialise in sequence; the failure has moved through three of them.

| stage | state |
|---|---|
| VBIOS / ATOM tables | **solved** — the controller starts and brands itself `AMD Radeon Navi23`, 512 MB, 128-bit GDDR6 |
| patch delivery | **solved** — OpenCore injects Lilu + this plugin into the boot collection, so every patch lands before `start()` |
| SWIP `BGM` | **complete** — all of `bgm_create`, VBIOS init, GDDR6 memory training |
| SWIP `GVM` | **complete** — UMC, VM, HDP and ATHUB all resolve handlers |
| SWIP `PSP` | SW_INIT **complete** |
| SWIP `SMU` | SW_INIT **complete** |
| `PSP` HW_INIT | **complete** — TOC accepted, TMR established, every firmware blob loads with status 0 |
| `SMU` HW_INIT | **complete** — via Apple's own dummy power-management back end |
| `GC` HW_INIT / `TTL::initialize()` | **complete** — the graphics core enumerates itself: `SE=1, numActiveCU=2, numActiveRB=1`, CWSR enabled |
| accelerator attach | **complete** — "Accelerator successfully registered with controller" |
| framebuffer aperture | **solved** — Apple reads MMHUB, which this part leaves unprogrammed; the GFXHUB copy has the real `0xf400000000..0xf41fffffff` |
| PowerPlay / power-up | **solved** — reports success instead of powering the GPU back down |
| RLC microcontroller | **running** — `RLC_CNTL=1`, `RLC_STAT=0x25`, all CP microcode loaded |
| `GC`/`SDMA` firmware-autoload gates | **solved** — both wait on a `BOOTLOAD_COMPLETE` latch nothing ever sets on this part |
| RLC safe-mode handshake | **solved** — the RLC never acks; upstream ignores that, Apple hard-fails on it |
| `TTL::initialize()` on a cold GPU | **complete and deterministic** — was a race on leftover state, now passes on a freshly reset device |
| **graphics ring (KIQ)** | **current blocker** — fully characterised: doorbell proven to reach the HQD (`DOORBELL_HIT=1`), MEC2 executing, ring translatable, no fault, and the MEC still reports `QUEUE_IDLE` |
| WindowServer | submits command buffers; panics in `AMDHWVMM::endVMPTUpdate` because no engine powered up |

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


## The three things worth knowing

**1. An APU's VBIOS is missing exactly two ATOM data tables.** Apple's driver wants a PSP
directory (master-data-table index 9) and a `vram_info` (index 28); an APU ROM has neither,
because its security processor lives in the SoC. Both can be synthesised — the parsers are
undemanding, and `populateMemoryConfig` fails only on a *zero* memory type or width, with no enum
validation at all. Apple never reads `ATOM_ROM_HEADER.pspdirtableoffset`, which is a tempting
red herring.

**2. Delivery must be the `ATY,bin_image` device property.** `readAtomBios` tries that property
first and the PCI expansion ROM second — and the ROM path bails when config offset 0x30 reads 0,
which is always the case under OVMF because EDK2 releases option-ROM BARs after enumeration.
There is a hard **64 KiB ceiling** on anything Apple will look at, so a real 1 MB discrete ROM
cannot be injected even in principle.

**3. HWLibs dispatches on the silicon's real IP-discovery versions, not the spoofed PCI id.**
That is why a device-id spoof gets you a long way and then stops dead. Most of the gates turn out
to be a single version field pointed at an implementation Apple already ships.

Full write-up with every VMA: [`findings/GPU-RE.md`](findings/GPU-RE.md).

## Layout

```
src/         RaphaelGPU.cpp     the Lilu plugin (patch table + boot-arg mask)
kext/        prebuilt RaphaelGPU.kext
tools/       mkrom.py           grafts the PSP directory + vram_info onto an APU ROM
             ocprop.py          edits OpenCore config.plist (device properties, boot-args)
             milestones.py      the patch ladder, re-verifies every pattern before deploying
             autorun.sh         walks the ladder unattended and classifies each verdict
             redeploy.sh        rebuild ROM, push to the ESP, restart, drain serial
             gpu-bind.sh        amdgpu -> vfio-pci, with the runtime-PM workaround
             recover-igpu.sh    recovery after the vfio runtime-PM oops
             build-kext.sh      cross-build a Lilu plugin kext on Linux
findings/    GPU-RE.md          the reverse-engineering write-up
             ip_discovery.txt   this chip's real IP block versions
```

## Two traps that cost real time

**Passing this iGPU to QEMU NULL-derefs the host kernel** unless the device is pinned awake
first. Opening a runtime-suspended device with vfio-pci hits
`vfio_pci_core_runtime_resume -> down_write` on kernel 7.2.x. It presents as a *guest* hang —
QEMU becomes a zombie, the container still reports "Up", the guest emits zero serial bytes — and
it is unrecoverable without a reboot, because `power/runtime_status` sticks at `resuming` and any
operation needing the device's PM lock then blocks uninterruptibly. Pin `power/control=on` before
anything opens it; `gpu-bind.sh` does this and a udev rule enforces it at boot.

**Lilu silently disables itself on an OS newer than it knows.** On Sequoia it logs
`automatically disabling on an unsupported operating system` and exits, taking every plugin with
it. `-lilubetaall` is required. Worth checking early, because it makes WhateverGreen and AppleALC
inert too.

## Measurement

The AMD kexts log through **two** channels and you need both:

- `os_log` — read with `log show --predicate 'senderImagePath CONTAINS "AMD"'`
- `kprintf` — reaches the serial port only with `DB_KPRT` set, i.e. `debug=0x108` in boot-args

Reading only serial produces a badly wrong picture: it looks like nothing beyond the GPU wrangler
runs, when in fact the whole stack loads.

Static analysis needs the **Kernel Debug Kit** for the exact build. On an installed system every
AMD kext bundle is a stub, with the code prelinked into `SystemKernelExtensions.kc`.

## Licence / provenance

Original work. Technique is informed by the published behaviour of Apple's shipping binaries and
by Linux's `amdgpu`; no code is copied from ChefKiss projects, whose licence terms differ.
