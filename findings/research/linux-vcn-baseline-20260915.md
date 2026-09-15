# Native Linux VCN baseline and macOS comparison — 2026-09-15

## Result

Raphael hardware H264 and HEVC encoding and decoding work on Linux. The sustained
H264 test produced 600 correct frames. **The same working device returns
`0xffffffff` for the cache BAR, soft-reset and LMA registers.** Those values do
not establish a dead VCPU, failed SRAM replay or firmware authentication failure.
The macOS encoder remains unresolved; this is a working reference, not a macOS fix.

## Identity and scope

- Boot: `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`.
- Raphael `1002:13c0`, `0000:7b:00.0`, `amdgpu`, `/dev/dri/renderD129`.
  `renderD128` belongs to another GPU. `power/control=on` throughout.
- Kernel `7.2.5-1-cachyos-bore`; Mesa `26.2.2-arch3.2`; FFmpeg `9.0.1`.
- Three bounded sessions through `tools/cycle.py linux-vcn`, using a user systemd
  service, sleep inhibitor, identity checks, capture-fatal/manual-stop/host-fault
  aborts and a 6000-second service limit. No QEMU, VFIO, reset, rebind or reboot.
- Sources: branch `linux-vcn-baseline`, commits `e7179b2`, `bdfcdd2`, `66b0727`.
  Last full host suite: 937 tests, OK, three skipped, before the active-state run.
- Boot journal includes suspend/resume before testing. Capture began after boot;
  it covers workload-triggered DPG startup, not initial boot-time PSP loading.

Artifacts under `/home/bogdan/macos-vm/run/`:

| Session | Directory | Additional observation |
|---|---|---|
| Baseline | `linux-vcn-c782d007` | Firmware identity, register and queue trace |
| SRAM | `linux-vcn-c782d007-sram` | Four 280-byte pre-submission SRAM images |
| Active | `linux-vcn-c782d007-active` | Five SRAM/shared snapshots, 600 frames, active register reads |

Each directory contains commands, stderr/stdout, result, kernel logs, raw trace,
trace loss statistics, input and output files, and hashes. `supplemental-sha256.json`
also covers analysis added after the original `sha256.json` was written.

## Functional validation

Each session ran software controls, explicit Raphael VAAPI H264/HEVC encoding,
software decoding of each output, hardware decoding of each hardware output,
and repeated both hardware codec workloads after idle gaps.

- Short tests: three NV12 frames, 1280×720, 30 fps, same quadrant pattern as the
  macOS probe. Every requested codec/control/repeat passed. Each content check
  compared 2,675,475 interior luma values; maximum error 1 for H264, 0 for HEVC.
- Hardware decoding required VAAPI surfaces followed by `hwdownload`; software
  fallback cannot satisfy that pipeline. Encoding explicitly used `h264_vaapi`
  or `hevc_vaapi` and Raphael's verified render node.
- Sustained H264: 600 frames / 20 seconds, FFprobe independently counted 600,
  software decode completed, and a subsequent streaming content check compared
  535,095,000 luma values with maximum error 1. See active session
  `h264-sustained-stream.stdout`, `sustained-content.json` and encoded MKV.
- Rate control differs from VideoToolbox: hardware QP20, software CRF18, no B
  frames. This qualifies these tested workloads, not every profile, chroma value,
  image edge, resolution, throughput limit, or macOS behavior.

## Capture and cleanup

All three sessions report capture complete to workload end and zero trace
overruns, commit overruns and dropped events on all 16 CPUs. Kernel workload
logs contain no GPU faults, reset or ring timeout. Workloads and capture
containers stopped; the private tracing instance and kprobe event were verified
absent after the final session. Only the existing `rgpu-inhibit` container remains.
Boot ID, amdgpu binding and pinned power remained unchanged.

Register tracepoints filter device ID `0x13c0`. Queue tracepoints are global and
may include the other GPU; do not attribute every queue event to Raphael.
Read-only kprobes were checked against the running amdgpu BTF, rather than
assuming a current upstream structure layout. The function takes
`(adev, inst_idx, ucode_id)`; SRAM CPU/current pointers are at absolute offsets
204560/204576, shared CPU/GPU at 204592/204600. Filter instance zero. Only the
pointer-delimited 70 SRAM words are valid image content; extra fetched words
are allocation tail and must not be interpreted as submitted registers.
The active session retains the exact `sram-probe` specification.

Instrumentation can affect timing; zero recorded loss does not imply every
hardware access is traceable. This is the CPU-side input to PSP, not a readback
of the post-PSP SRAM image or decrypted firmware.

## Direct corrections to the previous diagnosis

Active register snapshot during the successful sustained encode:

| Register (DWORD offset) | Linux value |
|---|---|
| POWER_STATUS `0x7e04`, before and after | `0x00000906` |
| PGFSM_STATUS `0x7e01` | `0x2aaa8aa0` |
| DPG_PAUSE `0x7e14` | `0x0000000c` (request and acknowledgment) |
| SOFT_RESET `0x7e84` | `0xffffffff` |
| VCPU cache BAR `0x823c/0x823d` | `0xffffffff` / `0xffffffff` |
| NC0 shared BAR low `0x8238` | `0x1fba0000` |
| VCPU_CNTL `0x7f56` | `0x0ff00200` |
| DPG LMA control/data `0x7e11/0x7e12` | `0xffffffff` / `0xffffffff` |

Evidence: active session `active-registers.txt`, traced accesses and the validated
600-frame output. The reason these selected reads are inaccessible/filtered is
not established. Do not use them as proof of a powered-off core again.

Linux's startup trace sends message 6 through DWORD address `0xec4142`, argument
0 through `0xec4262`, and receives response 1 at `0xec4261`. These are byte
addresses `0x03b10508`, `0x03b10988`, `0x03b10984`, matching our real SMU hook.
The earlier claim that macOS merely acknowledges requests in a dummy backend
does not describe that hook. A successful reply alone still does not measure a
physical power transition.

Linux's VCN firmware version is `0x04121015`, SMU `0x00625300`. Uncompressed
firmware SHA256 is `fe9f9507fa505b6d2f1f47f47d7846609dacfa0fa12993d873a2c5b1c4b44af9`;
payload SHA256 after the 256-byte outer header is
`d22915b1e6f16e5b44cd39b3bd503bc607312e4c94e34546b4935d3a6a5b4f9a`.
The payload exactly matches `build-support/vcn-firmware.json` in the macOS source.
See baseline `firmware-identity.json`. This rules out different input firmware
bytes; it does not prove identical PSP processing or placement under macOS.

## Startup comparison and remaining hypotheses

First active-session encoder bring-up, timestamps in kernel monotonic seconds:

1. `3971.097921`: SMU PowerUpVcn=6; response 1 at `3971.098152`.
2. `3971.098168`: DPG enabled, POWER_STATUS=`0x905`.
3. `3971.098192`: 280-byte SRAM input captured before PSP submission.
4. `3971.098720–3971.098739`: decode RBC control/BAR/read-write pointers set,
   with DPG stalled and then unstalled.
5. `3971.098754`: DPG_PAUSE request=4; `3971.098835`: readback=12.
6. `3971.098837–3971.098841`: encoder ring programming, then unstall.

Five first-ack delays in the final run: 81, 80, 81, 74 and 80 microseconds.
See `first-startup-registers.json`, `sram-shared-images.json`, `analysis-summary.json`.

| Stage | Working Linux | macOS evidence / implication |
|---|---|---|
| DPG SRAM input | 35 pairs, 280 bytes | Modified image 36 pairs, 288 bytes; size alone does not establish an error |
| Firmware windows | PSP-mode placeholders are zero | Software-mode candidate injects actual firmware/stack addresses; mode difference must be retained |
| Clock/reset/LMI | CGC_GATE=0, VCPU `1ff00200→0ff00200`, LMI_CTRL2=0 before release | These prerequisites already addressed; no sufficiency proof |
| Shared window | 4096 bytes, address `f4_1fba0000` in VRAM | 96 bytes, GART address `ff_bfdc3000` in candidate 260 |
| Shared ABI | flags `b40`, SMU byte at +58 =2, software decode ring disabled | flags `f47`, SMU byte=2; extra flags remain unexplained |
| Decode ring startup | Hardware RBC ring initialized before pause | Native requested queue is initialized after pause; no decoder-first hardware startup demonstrated |
| Pause | ACK within 74–81 microseconds | ACK wait times out at native caller +94db1 in DPG candidates |
| Output | H264/HEVC output validated | macOS accepts frames 0/1 then stalls on 2 without output |

Linux source sets `DEC_SW_RING_ENABLED=FALSE`; the advertised software-ring flag
does not mean it uses software decoding queues. Its VCPU allocation permits
`VRAM | GTT`, so this run's VRAM allocation does not prove GART is unsupported.
The 96-byte macOS buffer fits the currently identified 92-byte shared structure;
the Linux page-sized window is a concrete difference, not yet a proven fix.

The 24G830 disassembly confirms `_vcn_start_queue` (+88420) calls engine init,
marks the requested queue active, calls pause at +88487, then its hardware-init
callback at +88493. The engine's intervening +430 callback is only
`_engine_3_0_check_hw_info` (+94e30), not decode-ring initialization.
`_queue_decode_3_0_hw_init_ring` (+94fa3) contains the missing RBC setup sequence.
`_queue_initialize` (+88039) stores native-owned queue type 1 at manager+20;
whether this allocated decode queue exists at first encoder startup still needs
runtime verification. Earlier VideoToolbox decoder rejection occurred before
VCN initialization and did not test this hypothesis.

Next discriminating macOS experiment: observe that queue pointer, allocation,
callbacks and active state; when an existing native-owned inactive decode queue
is valid, test its native hardware initialization after engine initialization
and before the first encoder pause. Capture RBC writes, shared reset bits,
pause ACK and actual encoded output. Preserve ownership and active-count
semantics; do not invent a queue or initialize an active queue. If setup is
already present, or confirmed setup still leaves the same pause timeout, the
ordering hypothesis is weakened/rejected as a sufficient correction.
Test shared-window size/flags separately, rather than bundling hypotheses.

No macOS driver change or launch was made by these Linux sessions. The iGPU is
left on Linux. Firmware authentication, address translation and passthrough
remain possible areas to investigate, but an unavoidable below-driver boundary
and exhaustion of all driver-level options are not established.

## Source references

- Running-kernel BTF: baseline `amdgpu-btf.txt`; exact probes in active artifacts.
- Versioned primary reference source, downloaded under baseline `source/`:
  [Linux v7.2.5 vcn_v3_0.c](https://raw.githubusercontent.com/gregkh/linux/v7.2.5/drivers/gpu/drm/amd/amdgpu/vcn_v3_0.c),
  [amdgpu_vcn.c](https://raw.githubusercontent.com/gregkh/linux/v7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_vcn.c),
  [amdgpu_vcn.h](https://raw.githubusercontent.com/gregkh/linux/v7.2.5/drivers/gpu/drm/amd/amdgpu/amdgpu_vcn.h).
  CachyOS may carry additional patches; runtime trace/BTF take precedence.
- Apple decompilation and assembly:
  `/home/bogdan/macos-vm/re/decompiled-24G830/HWLibs-full/functions/`.
- Prior macOS artifact comparison: candidate 259/260/261/262 results under
  `/home/bogdan/macos-vm/run/` and
  [independent review](encoder-independent-review-20260915.md).
