# Live status — 2026-10-08

## Candidate333 completed: Metal-to-console pass

Run `a7fa79a29559deb6a80bedfb6ac658b1` / metal-181 / MODE2#266:
DMCUB hold/reservation passed, PSP unload returned0, native desktop Metal probe
passed with WindowServer accelerator ownership. Three generated1280×720 Metal
frames verified921,600 pixels each; independent QEMU captures of phases0/2 match
all1,843,200 pixels. The QEMU console window connected on the Linux desktop.
Full desktop capture remains blocked by the presenter's denied Screen Recording
permission (-3801); no TCC database was modified. Virtual display and awake
assertions worked. This is a presentation milestone, not full desktop qualification.

The harness reports valid `CORE_PROBE_PASS`. Guest-requested shutdown succeeded
(`exited-after-guest-request`), recovery reports `recovered` and
`authorizes_launch=true`. Results: `~/macos-vm/run/candidate-333-attempt-b-results`.
Next: repeat333 on the same host boot and qualify desktop capture after consent.

## Candidate332 host hang — investigation and correction

User reports a full host hang during candidate332 / metal-180, run
`dd40f35333452ac3e23f25210704f120`. Boot5074c0e5 ended; current boot is
`ba51b3c6-9420-4510-af69-38a42b3c79c7`. GPU is now owned by amdgpu; no new
GPU launch is authorized by old-boot receipts.

Preserved evidence: `~/macos-vm/run/candidate-332-host-hang/`. Guest serial ends
while sending PSP DESTROY_TMR (wire7), before its return, Metal startup or any
console pixel mapping. Bochs bridge enumeration had completed. Prior-boot
kernel journal records no panic/fault at the end; no archived pstore file is
available. This localizes the failure boundary, not the exact hardware cause.

Candidate331 had refused TMR init after an invalid framebuffer/DMCUB identity.
Removing host reservation in332 bypassed that protection; that change is rejected.
The earlier claim that disabling DCN alone explained331 was too strong.
Candidate333 now requires checked firmware hold and reservation for console TMR
access, independent of display enable flags. Build1.0.333 succeeds;1026 host tests
pass (three skipped). Fault injection confirms unsafe states cannot call PSP.
Hardware validation remains pending. On October8 the user handed the GPU to
VFIO. MODE2#264/#265 passed. Staging first refused an old-boot332 launch marker;
it was archived after matching its supervision/boot identity and verifying no
container/service survived. The next attempt (db5abf15b3ff977293f11bcad37863c0)
refused before QEMU exposure because boot-time kernel messages had rotated away.
The retained journal contains a complete Raphael system-resume sequence.
The harness now recognizes that bounded sequence (PSP/SMU/DMCUB/GFX/KIQ/SDMA/JPEG,
then suspend exit), rejects partial/wrong-device/failed resumes, and retains all
independent device/recovery admission checks. Candidate333 retry is next.
No reboot is requested. Card metal-181 is prepared;332 staging is withdrawn.
See [hang investigation](findings/research/console-tmr-host-hang-20261005.md).
Never resume332 or label it recovered:
there are no final capture, shutdown or recovery receipts after the host hang.

Prior331 stopped through guest-request shutdown and then passed the supported
MODE2/no-queue recovery path. Candidate332 had1025 passing offline tests;
those checks did not establish firmware-memory safety. [Console design](docs/virtual-console.md).

## Candidate330: correct HiDPI120 picture and HDMI audio

The user confirms correct colors and audible audio through the Samsung Odyssey
G95NC headphone/audio output. Awake macOS reports 1920×1080 logical / 3840×2160
pixels at 120 Hz. Audio device identity, default routing and successful playback
survive the tested HiDPI 120→60→120 switches without rerouting.

- Build: 1.0.330, source `933d60d9535cbfc7fea8f0709c29b4e502b54cef`, metal-178.
- Executable SHA-256: `20a1e10a123d42e89442e7e0ca096aef180e50c60c575bdbd50b7c1a4bc6235c`.
- Run: `433b6f803c826755d20396e08a011a2a`; artifacts: `~/macos-vm/run/candidate-330-results/`.
- Capture/identity: valid `CORE_PROBE_PASS`; no guest panic or DMUB delivery timeout.
- Shutdown: `exited-after-guest-request`; GPU recovered with `authorizes_launch=true`.
- Audio teardown: PCI command 2, bus mastering/DMA disabled, no errors.
- Host kernel capture: networking/firewall messages only; no recorded GPU/host fault.
- Final state: VM stopped; both functions remain on vfio-pci. No reboot or rebind.

The checked-in `kext/bin/RaphaelGPU` and manifest are the exact hardware-tested
build. README, roadmap, setup and release docs record this milestone for publication
to dev and main at the user's request. That end-of-day stop is historical; work resumed on October5.

Logs are not error-free: startup CAIL, DMUB capability-query and early GFXHDA
assertions remain, as do recurring PSP/HDCP status 4 errors. The FRL audio
framebuffer-event assertion is absent on330. Protected-content playback, arbitrary
hotplug/sleep, independent-host-boot durability and broader desktop qualification
remain open; the tested picture/audio path has no remaining observed blocker.

[Setup](docs/hdmi-status.md) ·
[Investigation and scope](findings/research/hdmi-hidpi120-20260924.md) ·
[Artifact hashes](findings/research/hdmi-hidpi120-evidence-20260924.json) ·
[Prior live status](findings/research/status-archives/status-before-hidpi120-audio-20260924.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Managed texture ownership | 96 cases;111,658,032 pixel comparisons; synchronized CPU writes and retained LOAD color contents, zero mismatches |
| Cross-process GPU events | Typed XPC import;33 consumer-first transfers,25,453,131 correct pixels |
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| Stock QEMU / PerfPowerServices | OpenCore/VirtualSMC fix passes two guest boots,0.0% CPU, latest0.86s; prior patched-QEMU evidence retained separately |
| Host regression | 1023 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Prior qualified280 driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).


## Remaining roadmap

1. Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
   then qualify login persistence. Remote90/120Hz delivery remains unproven;
   physical Samsung HiDPI120 now works.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. Existing clean stops do not qualify every failure mode.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release. Historical direct OpenGL hang and live Metal validation crash remain open.
4. HDCP, DisplayPort, broader monitors, other hypervisors and measured
   performance/release qualification. Samsung HDMI picture/audio have scoped passes.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in this tested setup;
PerfPowerServices was0.0% CPU on two guest boots. Automatic required-hardware HEVC
decode works; explicit GPU-ID selection remains limited. Main10 decode has scoped
passes; hardware encode is Main8. [Roadmap](docs/ROADMAP.md).


## Previous completed harness result (331; predates332 host hang)

- Output: `/home/bogdan/macos-vm/run/candidate-331-attempt-b-results`
- Verdict: `INVALID`
- Boundary: `recovery_lease_pool_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-333-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-333-attempt-b-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
