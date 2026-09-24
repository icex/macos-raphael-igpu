# Candidate313: late PSP DMCUB load

Candidate312 verified all source bytes but SEC_RESET bit16 did not stick; stopped
capture showed no changed CW0/1. Exact failing register was not logged, so this
identification is inferred from the first phase5 operation plus retained state.

Linux `amdgpu_dm_dmub.c` uses direct/backdoor load only when load_type is not PSP.
`amdgpu_ucode.c` sends inst_const_bytes starting at ucode_array_offset_bytes,
including the 256-byte PSP header and footer. PSP wire type is51.
Sources: local Linux238650ef, matching dcn315 register headers.

Exact Apple24G830 HWLibs map at3cddb4 maps Apple35 to wire51. Native
psp_cmd_km_submit5237e takes (psp, descriptor, response, async_slot=null).
Descriptor words:6, MCsource low/high, byte count, Apple35. It synchronously
waits, checks the response, releases its slot, and may make three bounded native
retries after a firmware error. Response status/fw_addr at words0/2/3.
The routine is the same one used by psp_np_fw_load_service54419.

The experiment captures the existing PSP context during successful native buffer
preparation. It executes late, under the existing serialized VCN/SMU init point,
after TMR setup and the tested display wake. It requires all16 GPCOM slots idle,
exact submit prologue and live firmware mapping. No PSP ring ownership changes.

Only rgpudmubpsp=1 plus rgpudmubreinit=1 selects the PSP path. The signed source is
written/read back at the reserved fb+7f000000 (MCf47f000000), length3a720. Existing
VBIOS/mail/trace/state upload checks remain. No SEC_CNTL or CW0/1 writes are made.
After native LOAD_IP_FW, require success, returned address within this guest's
recorded TMR, DMCUB still held, and both secure windows wholly within that TMR
in physical address space, nonoverlapping, correctly based and sufficiently big.
Only then configure CW3–6 and mailboxes, release firmware and require three
fresh version replies. Failure keeps the bounded hold path; exact register
mismatch telemetry is added. HDMI command delivery remains disabled.

The user authorized autonomous new builds and iGPU resets on2026-09-24,
superseding the earlier per-attempt approval clause. This does not remove
host identity, ownership, supervision, capture or cleanup checks.

Offline tests cover PSP refusal, out-of-TMR windows, unexpected reset release,
successful PSP placement and the absence of guest secure-window writes.

## Candidate313 result and314 continuation

PSP returned status0, firmware MCf47d900000; stopped capture confirms CW0
physical85d900000/3a520 and CW1 physical85d93a600/c5ae0 inside guest TMR.
PSP cleared DMUIF reset but left CNTL2=1 and ENABLE=0.313 stopped before startup
and reasserted the interface hold. CORE_PROBE_PASS; clean shutdown/recovery.

314 permits this observed interface state only with processor reset asserted
and ENABLE=0, reasserting DMUIF before continuing. In explicit held PSP-reload
mode, reservation validates but retires old secure CW0/1 storage; otherwise each
cycle would unnecessarily reserve another32MiB below the old TMR. All nonsecure
windows remain reserved, and the normal running-host reservation is unchanged.

## Candidate314 result

Run1e061e039b6dd6beacaf3f76494e4ace, MODE2#237: success1/phase8, three fresh
05003500 replies, fault registers0/0, selectors restored. Nonsecure windows
use the new reserved layout. Firmware scratch15 records a3a02 register timeout,
but GPINT completes; actual mailbox consumption is untested. Guest-requested
shutdown and recovery passed. Desktop probe JSON failed on an infinite numeric
value; this is separate from serial-proven firmware startup. HDMI delivery off.

## Candidate315: repeatable reload and HDMI delivery

314's firmware is now running. Before allocating/replacing TMR, the opt-in GMM
path validates windows, requests STOP_FW, then asserts processor/interface reset
and disables execution with readback. A bounded stop timeout may proceed to the
already-tested forced hold; inaccessible reads or failed hold refuse init. This
prevents execution from prior TMR during replacement. Existing owned nonsecure
windows are accepted only at the exact new layout with their expected sizes.

Firmware startup stays at the tested late VCN/display-wake point. Early DAL
commands remain log-only while held. After startup, validate the new empty inbox
with an unpublished reversible slot probe, then permit VBIOS type128 delivery.
The normal modeset commands occur after this point in314's serial timeline.
Each ring write remains readback-verified; timeout disables further delivery.
Raw MM_DATA reads preserve legitimate ffffffff data.

The desktop probe now emits null plus explicit nonfinite_numeric_fields paths
for invalid optional numbers instead of losing the entire report to an exception.
This changes reporting only; unavailable performance metrics are not zeroes.

## Candidate315 first hardware result

Run909d7c9412f825b8b7079f92b67f39be, MODE2#239: early hold, signed reload,
startup and three fresh version queries pass again. Reversible empty-inbox
verification passes.17 type128 commands consumed in10–820us, RPTR=WPTR=440.
No DMUB timeout or panic. Live read-only QEMU MMIO snapshot shows OTG0 scanning,
DIG0 HDMI enable/symbol clock on, HPD0 high. Later native system_profiler sees
Odyssey G95NC online/main at3840x1080/about59Hz. User visual check is pending.

CORE_PROBE_PASS; offscreen1000frames/736sampled pixels with zero mismatches.
Initial probe caught the physical display before attachment; late ioreg/profile
resolve that timing difference. Five-minute observation window ended normally:
exited-after-guest-request and recovery authorizes_launch=true. No screenshot
or software-online result is being treated as proof of a physical picture.
Repeat315-watch extends observation to5000seconds within the6000-second cap.
