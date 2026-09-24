# DMCUB reinitialization experiment — review proposal, 2026-09-24

**Authorization update:** The user subsequently said “ok proceed”, authorizing
implementation and the reviewed one-shot experiment. Candidate311 implements
that scope; delivery remains disabled. The initial review text below is retained.

**Originally prepared for review only. Not approved for execution, not staged, and not a
launchable candidate.** The user's 2026-09-24 instruction authorizes preparation;
it does not yet replace the earlier prohibition on guest DMCUB load/start/reset.
No hardware access was performed while preparing this package. No dev commit or
push was made. The baseline remains candidate310, local branch candidate-310.

## Question and decision

Does initializing the installed DCN3.1.5 firmware in fresh, guest-reserved VRAM
restore a real GPINT response? The first proposed run measures firmware startup
only. Apple-to-DMUB display command delivery remains disabled (`rgpudcn=1431`).
A Samsung picture is the following milestone, not the success criterion for this
first experiment. No HDMI-audio changes belong in this run.

Recommended implementation: one opt-in guest direct-load sequence matching Linux
`dmub_dcn31_reset`, `backdoor_load`, `setup_windows`, and `reset_release`, after
ordinary PSP initialization and the already-tested SMU display-wake step. Do not
reinstate the withdrawn early PSP DMCUB firmware-registration path from285.
This difference makes the experiment easier to isolate; it does **not** establish
that direct loading cannot freeze the host.

## Why this test

- 307–310 retained CW4/5/6 contents are identical. Fresh version commands receive
  no ACK. The advancing hardware timer and SCRATCH0=43 do not prove CPU execution.
- 308 acknowledged the register-interface timeout; 309 issued fresh queries;
  310 restored the prior host's 1000 MHz DCFCLK request with SMU response1 and
  returned1000. None restored firmware response. All three shut down cleanly.
- Installed firmware disassembly identifies the last recorded trace event as
  completion of VBIOS_SET_PIXEL_CLOCK; its retained request sets a zero clock.
- Linux's MP0 13.0.5 path sets boot_time_tmr=false and unloads TMR in PSP teardown.
  The old DMCUB code window lies inside that original host TMR. Loss of executable
  firmware ownership is a hypothesis; the exact failing transition is uncaptured.
- 285 froze the host after early firmware registration. 287 later froze before
  display initialization without that registration. This weakens a unique causal
  attribution to DMCUB, but does not qualify firmware reinitialization as safe.

The experiment is **recovery from already-unresponsive firmware**, not a controlled
reproduction of the original fault. A successful fresh boot answers whether this
route can restore service; it does not prove TMR teardown caused the failure.

## Pinned inputs and offline layout

[Machine-readable manifest](dmcub-reinit-review-20260924.json) pins source hashes,
firmware/VBIOS hashes, and the retained capture. The [offline planner](../../tools/dmcub-reinit-plan.py)
has no device-access or launch implementation.

Firmware: installed `dcn_3_1_5_dmcub.bin.zst`, version05003500. Uncompressed SHA256:
`c198f520748ed8ac0b8bec04c7d85d2962865c6bbe6c9a6791e661c23750b8d5`.
Linux metadata extraction removes the PSP header **and footer**: file offset512,
payload238880 bytes (0x3a520), metadata at0x3a6dc, BSS payload0. Copying the entire
firmware file or including its signing footer is not this experiment.

Firmware requests51328 state bytes and65552 trace bytes. Linux rounds allocations
to64 bytes and places windows at256-byte boundaries. Proposed allocation below
also reserves the extra inclusive top byte used by CW3–6, rather than aliasing it
with the next window. CW0/1 tops use size-1; CW3–6 tops use size, as Linux does.

| Window | Purpose | FB offset | Allocated bytes | Offset-register domain |
|---|---|---|---:|---|
| CW0 | Firmware code/constants | 0x7f000000 | 238912 | Physical FB |
| CW1 | Stack/context | 0x7f03a600 | 655360 | Physical FB |
| CW3 | Exact board VBIOS | 0x7f0da600 | 44544 | MC |
| CW4 | 8 KiB inbox + 8 KiB outbox | 0x7f0e5500 | 16384 | MC |
| CW5 | Trace/outbox0 | 0x7f0e9600 | 65600 | MC |
| CW6 | Firmware state | 0x7f0f9700 | 51328 | MC |

Reserved extent: `[0x7f000000,0x7f106000)`, within a proposed2 MiB limit ending
0x7f200000 and the driver's existing top32 MiB exclusion. This does not overlap
any captured host CW0/1/3/4/5/6 window or the previously observed host/guest TMRs.
These are **snapshot-derived addresses**, not permission to use them on a changed
layout. Live reservation/TMR/window validation is mandatory before any writes.

CW0/1 translation is MC address minus MC framebuffer base plus physical framebuffer
base: current CW0 offset-register address would be0x85f000000. CW3–6 retain MC
addresses, e.g. CW4=0xf47f0e5500. The physical and MC domains describe the same
VRAM; comparing one domain's address directly against the other domain's bounds
is invalid. All uploads go through the existing MM_INDEX transport, not a pointer
past the256 MiB guest BAR. CW2 is unused by DCN3.1 setup_windows; no new shared-state
or newer-generation feature is enabled (firmware metadata advertises none).

## Proposed one-shot sequence

The new implementation must remain default-off behind a dedicated boot argument
and experiment identity. Its narrow writer is separate from Apple's fenced CGS
register path. That existing fence remains enabled. Trigger only once at the
existing successful VCN initialization/SMU display-wake checkpoint, after native
PSP firmware initialization. Do not execute it on resume or retry automatically.

1. Keep cycle.py's identity, capture, inhibitor, MODE2 and recovery gates. Verify
   host reservation is active, no TMR/window overlaps the new allocation, both
   SMU mailboxes answer as expected, and firmware/ROM hashes match. Save the old
   windows, controls, faults, rings and trace. If the baseline GPINT already
   responds correctly, skip reinitialization and preserve that working state.
2. Log the reset boundary. Following Linux, request STOP_FW via GPINT0x10020000;
   bound each ACK/DEADDEAD/PWAIT wait to100 ms. Record a timeout explicitly.
   Linux permits a forced DMCUB reset after this timeout; approval must include
   that operation, since the current firmware likely will not acknowledge STOP.
3. Assert DMCUB_CNTL2.SOFT_RESET (index36c0 bit0), assert
   MMHUBBUB_SOFT_RESET.DMUIF_SOFT_RESET (index3802 bit8), and clear
   DMCUB_CNTL.ENABLE (index36b6 bit16), preserving unrelated bits. Confirm each
   state before uploading anything. Reset INBOX1/OUTBOX1/OUTBOX0 pointers,
   SCRATCH0 and GPINT_DATAIN1 as Linux does. Do not reset the entire MMHUBBUB.
4. While held reset, zero the fresh allocation, upload only the pinned code
   payload and VBIOS, and read back every written dword. Verify complete payload
   hashes and initialized regions before release. Old host buffers remain intact.
5. Assert SEC_RESET (SEC_CNTL index368e bit16); set translated CW0/1 offsets,
   bases and inclusive tops; clear SEC_RESET and set MEM_UNIT_ID=0x20, preserving
   the other security fields exactly as Linux's direct-load path does. Program
   CW3–6 with MC offsets and the manifest's bases/tops. Mirror CW5 into REGION5
   with top=trace-allocation-size-1. Validate all readable fields.
6. Configure inbox1 at64000000/size2000, outbox1 at64002000/size2000, outbox0
   atA0000010/size10030. Set SCRATCH14=80: Linux's baseline enable_dpia bit,
   matching the retained host option. It is not an exception flag. Do not copy
   SCRATCH15=5ecf from the old timeout report; use the direct-load default PSP
   version0. Release DMUIF reset, set ENABLE and TRACEPORT_EN, then clear DMCUB
   SOFT_RESET in Linux order. Preserve unrelated control bits.
7. Poll fresh SCRATCH0 DAL_FW|MAILBOX_READY for100 ms, then issue GET_FW_VERSION.
   Require a real10010000→00010000 ACK and version05003500. Repeat twice,10 ms
   apart. Record phase timestamps, controls and fetch/write fault registers.
   Capture fresh firmware state/trace; a hardware timer alone never passes.
8. Keep display delivery disabled even if startup passes. Run the standard Metal
   core probe, then request ordinary guest shutdown through the harness. Report
   firmware response, Metal function, capture and cleanup separately. Compare
   stopped-device state afterwards; do not call it responsive without a fresh
   ACK. No automatic second firmware attempt on this boot.

Addresses above are DWORD register indices. The manifest stores exact window
values. New register writes must use checked read/modify/write and bounded polls;
all-ones reads or identity changes stop the sequence.

## Abort and recovery behavior

Before reset, any failed check leaves DMCUB untouched. After reset assertion,
any mismatch prevents release: leave the processor halted, restore MM_INDEX
selectors, log the exact last completed phase, and stop through the harness.
If startup fails after release, make one bounded attempt to hold DMCUB/DMUIF in
reset and stop. If MMIO is inaccessible, issue no further speculative writes.
Do not replay old ENABLE/windows as a supposed rollback into potentially invalid
firmware memory. Reset cannot be treated as a reversible register edit.

Existing native recovery runs first. If the guest never published a usable lease,
the previously verified stopped-device MODE2/no-queue recovery remains available
under its existing conditions. Its receipt proves GC/SDMA/PSP cleanup, **not**
DMCUB recovery. No automatic vfio→amdgpu cycle, bus reset, privileged operation,
or reboot is part of this experiment. A host-wide fabric lockup can defeat the
supervisor and software cleanup; this proposal does not remove that risk.

The firmware can program display hardware during its own startup even with host
HDMI commands withheld. Therefore this is not a promise of a PHY-free experiment.
The direct-load path and new memory placement are source-supported but untested
on this host under VFIO. Linux reference is7.3.0-rc3; running host is7.2.5.

## Review outcome and remaining implementation

Approve/reject the **scope** above: one guest direct-load attempt, including forced
DMCUB reset after an unanswered STOP, with display commands disabled. Preparation
approval alone does not authorize these hardware actions. There is no executable
loader or launch card in this package, so it cannot accidentally run.

Before an approved launch: implement this sequence and its failure paths, exercise
write-boundary/address-domain/readback/timeout failures with a fake transport,
run the host suite, build and pin a fresh local candidate, and pass the harness
preflight. Keep dev/pushes on hold until meaningful progress. If implementation
changes this scope or reveals a new ownership conflict, revise the review first.

Primary source: Linux commit238650ef6c7c7cca08e032527329424c9fbd70e5,
`drivers/gpu/drm/amd/display/dmub/src/{dmub_srv.c,dmub_dcn31.c}` and
`display/amdgpu_dm/amdgpu_dm_dmub.c`; exact hashes are in the manifest.
Related evidence: [retained timeout audit](dmcub-register-timeout-20260923.md),
[original285 incident](dcn315-dmcub-host-crash-20260917.md),
[287 counterexample](dcn315-first-init-20260923.md).

## Candidate311 result

Reset succeeded; upload stopped before window reprogramming/startup. The raw
stopped-device capture matches the code and initial buffers through the first
VBIOS all-ones word at fb+7f0dd340. The subsequent word remains untouched.
The inherited indirect reader used CGS readValidateReg32, whose all-ones sentinel
handling is unsuitable for arbitrary firmware data. See24G830 Framebuffer
readValidateReg32 at1ca34, validateHwState at1c77c and raw hwReadReg32 at1c9ba.
The latter returns the unmodified register word. A fix must use it for MM_DATA
and retain strict register-access checks separately. No blind retry was made.
Metal and capture passed; clean guest shutdown and native recovery succeeded.
DMCUB itself remains held reset.
