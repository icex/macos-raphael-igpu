# Reboot-free reset and TigerVNC audit — 2026-09-14

The initial reboot recommendation was premature and is retracted. The host remains on boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`. The retained candidate230 repeat host snapshot
(`run/candidate-230-attempt-repeat-results/host-before.json`, SHA-256
`65a797408ef6c06a2edcdb45d8422876009e5883437138c3ec2e4c50d9603af6`) recorded successful
amdgpu initialization before journal rotation. The coordinator now validates this exact
snapshot against live host identity; a fresh MODE2 reset is still required separately.

All run paths below are relative to `/home/bogdan/macos-vm/`.

| Launch | Run id | Reset | Results |
|---|---|---|---|
| 41 | `4aff2d26b7fe53a1a91428c00e5d54c3` | 65 | `run/candidate-230-attempt-tigervnc-results/` |
| 42 | `7557ae12fd712a5043d7c249b2503628` | 66 | `run/candidate-230-attempt-tigervnc-restored-results/` |
| 43 | `28acce9ab6009fc2d1afeee9219cec6f` | 67 | `run/candidate-230-attempt-tigervnc-only-results/` |

The kext executable/build stayed identical to candidate230's successful repeat. Run 41's
`running-identity.json` equals that repeat's record in every field, including QEMU argv hash.
Functional boot arguments match; only run nonces change. The `XTCOW p=0 w=0 r=0 v=0`
records indicate KERN_SUCCESS for all four operations, not failed verification.

## Independent outcomes

**Function:** none of the three desktop probes completed; `probe.json` records transport exit
1 and no guest-agent response. Run 41 authenticated over TigerVNC after correcting the stale
helper-script account, but Screen Sharing reported no active display dimensions. Run 42's
`display-log.txt` explicitly records `good authentication`; no usable desktop followed.
Run 43 failed before any viewer connection. Its `pre-viewer-observation.txt` and
`vnc-sockets-at-failure.txt` establish that control condition.

**Observation/identity:** exact build and running topology were captured. In run 41,
`windowserver.sample.txt` shows the main thread in Metal command-buffer shared-memory creation
through IOConnectCallMethod. Serial channel dumps show pending SDMA/VMPT work, including
video-encoder clients; graphics ring RPTR/WPTR are equal in the captured snapshots. This is
not sufficient to identify the first causative packet. Run 43's `guest-state.txt` still shows
VTEncoderXPCService blocked without a Screen Sharing process or connected viewer. The
concurrent-viewer hypothesis is therefore insufficient and is not retained as a diagnosis.

**Guest state restoration:** run 41's `display-restore.txt` proves the original global and
user ByHost WindowServer files were restored, with SHA-256 values `361f982d…` and `4ad8e580…`
respectively and preserved ownership. The backup directory was retained. Run 42 confirms
both destinations exist. No unverified Screen Sharing preference preimage was invented.

**Cleanup:** all three guests stopped via the existing harness path and reported `forced`.
Each harness recovery receipt reports `incomplete`. The host remained reachable and on
vfio-pci with power pinned on. Final MODE2 receipt `run/mode2-reset-68.json` confirms
CP_STAT=0 and RLC_CNTL=0 after run 43; this is a successful documented reset, not a clean
macOS shutdown or proof that every engine's future workload is qualified.

**Qualification:** INCONCLUSIVE / probe_completion_missing for all three. Historical passing
copy matrices remain valid historical evidence, but the present desktop is not qualified.

## Next observation

Identify the initiator of VTEncoderXPCService in the no-viewer guest and reconstruct the
first SDMA/VMPT stall against the successful repeat, including guest persistent configuration
and workload. Do not make another nearby GPU patch or infer that reboot is required from a
missing journal record. The user explicitly prohibits host reboots.

## Encoder requester identified: launch 44

Attempt `encoder-trace`, run `c5305130649b36a7d6959e28db8bb914`, MODE2 69,
guest boot `7A365A8E-4B80-45F5-9AB1-19AB5452615F`. Results at
`run/candidate-230-attempt-encoder-trace-results/`. No VNC viewer.
`prior-client-518.txt` identifies run42 client518 as RustDesk. `client-trace.txt`
identifies current parent467 `/Applications/RustDesk.app/Contents/MacOS/RustDesk`,
child548 `RustDesk --check-hwcodec-config`, and encoder562 with XPC peer548.
This proves who requests HEVC initialization, not the first defective GPU operation.
Run42's first dump has kernel_task SDMA26 TS6 sent55.923502, VMPT16 TSc4
sent55.924113, encoder SDMA17 TS1 sent55.924637, and WindowServer paging12
TS59 sent55.931510. Timestamp order alone does not prove a causal engine dependency.
The successful repeat has no FirstPendingCB/hang dump; identical startup warnings
are therefore not sufficient diagnoses.

`startup-before.txt` contains the ByHost loginwindow `TALAppsToRelaunchAtLogin`
array including RustDesk. Removed only that entry; Finder/Safari/Terminal remain.
Guest backup: `/Users/bogdan/rgpu-startup-backup-encoder-trace/` (original plist
SHA256 `9c40199c5769c130cbedfe9548f9dd9a74f86647d5a5969b6481ad8e6c08c2ae`).
New plist SHA256 `d14c6abc355bcb4a68e8f1cae727e4f837696fd3f0af95878cd95a59d759b509`,
verified in `startup-change.txt`. App remains installed. This is a reversible
controlled startup intervention, not yet a validated fix.
Probe completion missing; exact identity captured; forced shutdown and incomplete
harness recovery. VM stopped through stop-requested. Launch allowance consumed.

## Launch45: desktop returns, corruption persists, hardware H264 stalls

Run `c26817033620e52bd530b0129d19bbf6`, reset70, no initial VNC viewers.
Results: `run/candidate-230-attempt-without-rustdesk-results/`. RustDesk absent.
Desktop probe passed=true, both fresh-process copy matrices completed. TigerVNC
authenticated and displayed the desktop; menu interaction visibly responds.
User and captured `tigervnc-menu-corruption.jpg` show green/purple corrupt menu
pixels. Thus CORE_PROBE_PASS does not establish desktop correctness. Raw RFB was
selected; HEVC encoding is not required for that visual symptom. SSH screencapture
omits application windows (screen_capture_preflight=false); it cannot adjudicate
compositing vs capture here. RustDesk removal is only a startup-stall workaround.

User explicitly requested fixing corruption and all broken encoders. The new bounded
`tests/video_codec_probe.m` in candidate233 compiled in guest. Software H264/HEVC
encoded and software-decoded3 frames each, max luma errors1/0, 2675475 checked per
codec. Hardware H264 on registry4294968030 selected h264.gva and hardware=true.
It accepted submissions0/1, blocked in submission2, emitted no encoded callback,
and hit its90s deadline. See h264-hardware.jsonl and encoder-h264.sample.txt.
Sample: VAUveEncoder::createSession -> IOAccelResourceFinishEvent, and a separate
thread waits for a Metal command buffer. No independent HEVC test yet; earlier
RustDesk HEVC creation already correlates with the same kind of VMPT/SDMA stall.
HEVC-alpha remains untested.

The first pending paging IB is already captured by the existing XB callback!
cb1 VA0xffc0ce2940,50 dwords, two checksum-tagged passes. It writes MMHUB2.0
registers based at0x13200: context2 root0x1392f/0x13930 =0xf41b09c000, range
0x1394f/50 and0x1396f/70, invalidate engine6 range0x13913/14, request0x138e9
value0x00980004, then POLL_REGMEM at byte0x4e3ec (register0x138fb) for bit2.
The local Linux mmhub2.3 headers used for Raphael2.4.1 instead map segment1 at
0x1a000, context2 root0x1a950/951, engine6 request0x1aa31 and ACK0x1aa32.
Apple X6000 fillVMRegisters constructs the old214-dword hub table atVMM+0xef8;
its HWLibs does have a separate mmhub2.3 initializer. Candidate230 root repair
explicitly excludes hub1. The pending encoder fill is behind paging progress;
do not label its memory-fill packet itself the first fault.

Shutdown forced; harness recovery incomplete. VM stopped, final MODE2 reset71
CP_STAT=0/RLC_CNTL=0, same host boot. No host reboot or vfio binding cycle.

Candidate233 implementation: opt-in rgpummhub=1 validates all214 register-index
words at native VMM+0xef8 before replacing the table. Every mapping was checked
against identical register names in Linux mmhub2.0/2.3 headers. Default hub0-only
root behavior is retained; explicit hub1 root repair requires the corrected table.
No MMIO, allocation or logging added to prepareVMInvalidateRequest. Bounded
observations are drained by the existing worker. Whole-table mismatch aborts VMM
initialization. This is untested on hardware and does not claim to fix corruption.


## Launch46: corrected MMHUB removes paging stall; VCN still blocks

Candidate233 sourcef7e7ec49533e3444447a2ef62b101bb9562b973b, run
953a71a247c9dfea622129c4a598026c, buildaeadd6aac6584078b7fd944c58d82459,
executable963290beaa0e9726a6bd52b3bdd869f8669da8a6977b089b666b9c8396a79c75.
Reset72; guest9748C797-DA5C-42CC-B96D-51635C16E2E7; registry4294968047.
Results run/candidate-233-results. Serial MH table result4 corrected1, root2
0x1a950 req6 0x1aa31 ack6 0x1aa32. Desktop probe passed. Hardware H264 gva
hardware=true, prepare0, two submissions accepted, third blocks, deadline90,
no encoded callbacks. First pending channel15 VCN0EncLLQ TS0->1; SDMA12
234/234 and VMPT16 80d/80d completed/submitted. Other graphics/compute queues
complete and WindowServer remains responsive. Thus shared paging correction is
functionally supported, while VCN initialization/submission remains defective.
No independent HEVC or alpha run on this state. SW VCN dump7e04=901,
80e0/80e1=deadbeef; this alone does not distinguish firmware, registers or gating.
No visual corruption retest; launch45 remains unresolved. CORE_PROBE_PASS applies
only to earlier desktop probe. Shutdown forced; recovery status recovered.
VM stopped; final MODE2 reset73 CP_STAT0/RLC_CNTL0, same boot, no host reboot.
Allowance46 consumed. Regression suite926 tests/3 skipped passed before exposure.
