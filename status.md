# Live status — 2026-10-09

## Candidate341: first libvirt launch refused before QEMU

Run `38ca74a82e750f36f3f70fc6859951d3`, metal-187, build1.0.341,
MODE2#279 on bootba51b3c6. The planner refused the real uppercase NAT MAC
address before starting libvirtd or creating QEMU. No guest execution or serial
capture occurred. The launcher/container stopped; no ordinary GPU recovery
receipt was produced. Artifacts: `run/candidate-341-results/`, including preserved
`launcher.log`. The ledger contains a launch reservation; same-boot admission
must reconcile that reservation or obtain supported stopped-device recovery
before another launch. No reboot or rebind has been requested.

The parser now accepts hexadecimal MAC case while preserving exact native argv.
The actual failed launch command parses successfully offline (14devices,8vCPUs,
12000MiB). The schema8 empty-capture qualification now follows the current
no-count ledger policy while preserving complete stopped-device scans and hashes;
cycle forwards the prior evidence explicitly. Full regression suite after these fixes:1,102 tests pass,3 skipped. This is not yet a recovery pass. Earlier real software controller tests passed valid
resume/poweroff and wrong-process permit cleanup; host release ordering tests
also pass. Full suite before this run:1,095 tests,3 skipped;76 staging tests pass.
This remains **unqualified for libvirt-managed accelerated macOS**. Native driver
source is unchanged from340. [Handoff evidence](findings/research/libvirt-entry-handoff-20261009.md).

## Candidate340: native accelerated SPICE desktop after host resume

Run `892ec42661ae367e299f60d55c9da9ee`, metal-186, build1.0.340,
same bootba51b3c6, MODE2#276. The opt-in empty-firmware path verifies reset-held
empty code windows, native memory accounting and the pre-PSP guard. Native desktop
Metal passes, with WindowServer accelerator ownership. SPICE shows3840×2160
pixels/1080HiDPI; a180-second material workload completes2,066 event iterations.
Separate SPICE input checks receive exact text RGPU336 and a click at(295,130)
inside the test field. Guest display/system awake assertions remain active.
Copied-frame samples are not viewer fps; performance remains open.

Capture: valid CORE_PROBE_PASS, no earliest failure. Shutdown:
exited-after-guest-request. Ordinary native recovery: authorizes_launch=true.
VM stopped; no reboot/rebind. Results: candidate-340-results. The real host
sleep:idle inhibitor remains active across development. The same-build repeat also passes (below); full VM-manager lifecycle
integration and measured console performance remain unqualified.
[Evidence](findings/research/console-spice-native-evidence-20261009.json) ·
[Driver scope](findings/research/console-empty-firmware-20261009.md).

Repeat attempt340b (run62832a3704054a540c0ff3871558e237, MODE2#277)
was refused before QEMU/VFIO exposure because the live journal rotated past the
amdgpu initialization record. No GPU ledger entry or recovery receipt was consumed.
The existing retained-evidence mechanism now pins340's same-boot host-before
snapshot; no gate is removed.

Repeat340c, run `23ac0eeacee8dffe827be1a645e6416c`, MODE2#278, same build/boot:
native desktop Metal and automatic presenter startup pass. SPICE again shows the
3840×2160 desktop; awake assertions are active. Capture valid CORE_PROBE_PASS;
shutdown exited-after-guest-request; native recovery recovered, authorizes_launch=true.
Results: candidate-340-attempt-c-results. VM stopped. The tightened harness holds
sleep:idle itself, while rgpu-work-awake remains active between runs. Full host
suite:1,033 tests pass,3 skipped. Next: preserve network descriptors and supervised
ownership in libvirt lifecycle integration; independently measure console delivery.

Earlier console runs and the post-suspend refusal are preserved in
[the October9 archive](findings/research/status-archives/status-pre340-repeat-20261009.md).

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

The September publication on main contains the tested330 build. The current dev
binary is340, tested on the console path; its physical HDMI path has not been
independently rerun. That end-of-day stop is historical; work resumed on October5.

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
| Host regression | 1033 tests OK, three skipped |

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

1. QEMU console resize, measured frame pacing/input latency, and supervised
   libvirt/virt-manager integration. Automatic guest-login startup passes one repeat.
   Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
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


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-341-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`
