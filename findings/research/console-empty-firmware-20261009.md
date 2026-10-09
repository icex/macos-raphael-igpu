# Candidate340: console initialization with empty DMCUB code windows

## Observation and hypothesis

336e uses the same driver/helper as the passing336d session, but follows a host
suspend/resume. Its reservation hook reads CNTL=0, processor reset=1, interface
reset=0 and boot scratch=0, then refuses before PSP TMR replacement. After clean
guest shutdown and supported no-queue recovery, a separate stopped-device snapshot
reads CNTL=0x90000, processor reset=1, no firmware version, empty CW0/CW1 and empty
regions0–2. Old mailbox mappings remain. The snapshots are at different times;
do not claim the later CNTL value was present at the earlier refusal.
Artifact: `~/macos-vm/run/c339-post-resume-dcn.json`.

Hypothesis: the console requires a distinct path when executable firmware windows
are empty after host resume. The prior held-firmware path intentionally requires
version0x05003500 and validated code storage. Removing its guard is not the fix.

## Narrow opt-in experiment

`rgpuconsolecold=1` is effective only with console mode. Before any MMIO write,
validate native framebuffer size, visible aperture and existing reservation.
Require CPU reset already asserted exactly, zero boot/version and entirely empty
code windows CW0/CW1 plus regions0–2. Reject unknown control/interface values.
Complete the interface-reset/disable order without releasing processor reset,
verify every write, and repeat the empty-window and held-state checks.

Inactive mailbox ranges must still be empty or wholly inside known memory bounds.
There is no mapped host executable firmware to preserve in this separate case;
retain the native allocator's existing reservation and verify its actual cursor
and accounting after the original callback. The normal retained-firmware path is
unchanged. Immediately before PSP, require successful native memory accounting,
empty executable windows again, enable clear and both resets asserted. No DMCUB
firmware is loaded, started, or released from reset by this path.

Linux source basis (local `/home/bogdan/src/ref/linux`):
`display/dmub/src/dmub_dcn31.c`, dmub_dcn31_reset asserts processor reset, asserts
MMHUBBUB DMUIF reset, then clears DMCUB enable. setup_windows ignores CW2; backdoor
load sets CW0/CW1 executable mappings. `amdgpu/amdgpu_psp.c`, psp_resume starts PSP
and loads non-PSP firmware anew. Those are source observations, not a successful
Raphael host-resume qualification. Candidate340 specifically leaves DMCUB stopped.

The next live discriminator is successful native reservation and PSP return,
followed by the independent desktop Metal probe and native ownership publication.
Any inaccessible register, partially populated code window, changed identity,
failed reset readback or invalid memory range must refuse before PSP. A visible
software-fallback desktop does not pass this experiment. Recovery remains the
ordinary harness plus the separately validated no-queue fallback if init refuses.

## Prepared artifact

Build1.0.340, source `fc308455fea0e25e411676b70d9f6f4f2485f686`,
build ID `f5f8285a85f2437285c0aa6a5daa29e1`, executable SHA256
`659c2ec9ba1236fa160a8c101d2cb54675fee0d020d7a06982dafe1577d6632d`.
Full host suite after driver changes:1032 tests pass,3 skipped. Metal-186 pins
this source and enables only the reviewed console cold-state option on SPICE.
The binary remains experimental; the first native result is recorded below.

## First native result

Run892ec42661ae367e299f60d55c9da9ee, same host boot, MODE2#276:
empty firmware hold=1, CNTL0x80000, processor reset1, DMUIF0x100. Native
reservation retains0x200000, adds0, cursor0x7fe00000; accounting is ready before
PSP TMR replacement. Native PSP returns0. Independent desktop Metal probe and
WindowServer accelerator ownership pass. SPICE captures3840×2160 desktop pixels,
with moving material, keyboard modifiers and correctly positioned mouse input.

Capture is valid CORE_PROBE_PASS; clean guest-request shutdown and ordinary native
recovery succeed, authorizes_launch=true. This is one post-resume successful run,
not general suspend/resume or crash qualification. The repeated same-boot run is
next. See console-spice-native-evidence-20261009.json for immutable artifact hashes
and input/workload limitations. No DMCUB start or firmware load was added.

The tightened sleep-inhibition harness and focused viewer pass the full host
suite:1,033 tests,3 skipped. The first run exposed an obsolete idle-only test
expectation; it was corrected to assert rejection of idle-only inhibition.
