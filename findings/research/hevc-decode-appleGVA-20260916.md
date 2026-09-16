# HEVC decode: observed capability failure, bounded driver fix, qualification

Updated 2026-09-16 after candidate 276 control and two candidate 277 runs.
This replaces the earlier conclusion that no bounded kext fix was possible.

## Corrections to the earlier investigation

1. Run 5cb7876d did **not** demonstrate HEVC hardware decode. Its exact embedded
   source in `~/macos-vm/run/candidate-275-results/video-codec-probe-hw-hevc-command.json`
   sets `kVTVideoDecoderSpecification_EnableHardwareAcceleratedVideoDecoder:@NO`.
   It verifies hardware **encoding** by software decoding the result. The `hw`
   argument refers to the encoder. Its serial context is codec=7/channel=10/encode=1.
   No intermittent-success hypothesis follows from this run.
2. The actual PCI node was **S30**, not display. The display node observed in the
   name search is `IOService:/IOResources/IOKitRegistryCompatibility/display`.
   It has no HEVC capabilities and is not an ancestor of the accelerator.
3. One Metal device was enumerated consistently by the diagnostic. A flaky
   multi-device topology was not established as the codec failure's cause.
4. Failure in userspace before video context creation did not rule out a kext
   fix: the search depends on names/properties published by kernel services.

## Controlled observation and implementation

Candidate 276 retains candidate 275 GPU behavior. Run
`84e8479030e7d41098a3751309dc2d26`, MODE2 #139, boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`:

- `~/macos-vm/run/candidate-276-results/capability-lookup-output.txt` reproduces
  the name filter and `IORegistryEntrySearchCFProperty(..., IOService, key, 0, 1)`.
  The only accepted name is the unrelated compatibility display node: searches
  return null. The real GPU path is PCI0/AppleACPIPCI/S30@6. Directly matching the
  Metal registry ID finds the accelerator and full valid capability dictionary.
- `hevc-baseline-output.txt` records HEVC create -12913; requiring the registry ID
  returns -12906. Its post-log wrapper omitted the terminal exit marker, so the
  wrapper exit was unqualified; the explicit decoder-create records remain usable.
  The helper's post-log exit handling was corrected for subsequent work.
- CORE_PROBE_PASS, guest-requested exit and recovered receipt. Kernel messages
  include container/network activity, not a GPU/host fault.

AppleGVA 24G830 function `0x7ffa06717bec` only examines nodes whose names start with
GFX0, IOPP, IGPU or display. The recursive search descends into their children.
The "IOGVACodec not set" message at `0x7ffa06717e60` actually reports a null
**IOGVAHEVCDecode** lookup. This was checked against disassembly, not only Ghidra's
inferred pseudocode (which incorrectly renders the iterator handle as zero).

Candidate 277 adds 14 lines in `wrapHwEngInit`. Under the existing SDMA topology
and exact Raphael hardware marker guards, it renames only S30 to GFX0 in the
IOService plane. The marker includes vendor 1002, spoofed device 73ff, ATY ROM
presence and the exact rgpu,raphael-target marker. No new native function route,
register access, property fabrication, ACPI rename or topology restructuring is
introduced. Already-renamed nodes are left alone. The resulting name is logged.

The hypothesis predicted that this name correction would expose existing
capabilities and permit context creation. Both observations occurred: the lookup
probe now finds the dictionary below GFX0, and serial records HEVC decode contexts
codec=4/channel=8/encode=0. Hardware-required VideoToolbox sessions decode verified
frames and report UsingHardwareAcceleratedVideoDecoder=true.

## Qualification

Same executable SHA256:
`1e50cf16c8ac4333a84b84321394cce07b28c94947e1264aa5b86463b588b17a`.
Build ID `53e6460029a64be299f92c823efa785d`, source commit `a77252f`.

- `~/macos-vm/run/candidate-277-results`, run
  `532ac6d9eefc560e06f6df973245fd67`, MODE2 #140.
- `~/macos-vm/run/candidate-277-attempt-repeat-results`, run
  `c1b774b2087ecdcd4b3edd2d25e788c7`, MODE2 #142.

These are distinct fresh guest boots on the same host boot. Both have authenticated
build/capture identity, CORE_PROBE_PASS baseline, guest-requested shutdown and
recovered receipts bound to the corresponding run. No host/GPU fault was reported.
Prelaunch attempts #138 (card registration) and #141 (missing retry artifact copy)
never launched QEMU and consumed no exposure ledger entries. The three actual
exposures in this investigation were 276, 277 and 277 repeat, bringing this host
boot's total to seven under separately recorded allowances.

| Guest | Workload | Frames | Maximum checked luma error |
|---|---|---:|---:|
| First | HEVC software encode → hardware decode, 720p | 600 | 0 |
| First | HEVC hardware encode → hardware decode, 1080p | 600 | 1 |
| First | H.264 hardware encode → hardware decode, 1080p | 600 | 1 |
| First | HEVC hardware encode → hardware decode after H.264, 720p | 600 | 0 |
| Second | HEVC hardware encode → hardware decode, 1080p | 6000 | 1 |
| Second | HEVC software encode → hardware decode, 1080p | 600 | 0 |
| Second | H.264 hardware encode → hardware decode after HEVC, 1080p | 600 | 1 |

All seven sustained probes exit 0, verify hardware selection, account for every
frame uniquely and pass their luma readback. Total 9600 sustained frames. The
6000-frame case alone checks 12,172,950,000 luma values. An additional initial
3-frame auto-selected hardware HEVC decode passed with zero error; the combined
variant probe still reports overall false because its explicit-registry-ID case
is rejected. Do not mislabel that combined probe as passing.

Machine-readable outputs, result records, command/output digests, binary identity,
guest boot UUIDs and independent cleanup outcomes are retained in
`hevc-decode-qualification-20260916.json`. Host suite: 937 tests, OK (3 skipped).
The sustained workload uses Main 8-bit 4:2:0 synthetic luma patterns, excludes
narrow lossy edges, and runs sequential encode/decode sessions. It is not a
qualification of arbitrary real-world content, chroma fidelity, Main10, concurrent
sessions, crash recovery, full desktop rendering or physical display output.

## Why explicit RequiredDecoderGPURegistryID still fails

The repeat run's `decoder-classification-output.txt` calls the real VideoToolbox
classification functions: **slotted=0, external=0**. VTCopyVideoDecoderList lists
HEVC HW Decoder / com.apple.videotoolbox.videodecoder.hevc.gva as hardware, without
a per-device registry ID.

In VideoToolbox 24G830 `0x7ff812cde9d1`, decoder registration creates copies carrying
VTDecoderMetalRegistryID only for slotted or external Metal devices; a built-in
GPU retains the global entry. In `0x7ff8129dc238`, an explicitly required registry
ID filters against that field; missing fields read as zero, so a nonzero required
ID removes the global entry and yields -12906. This is a separate selection
constraint, supported by runtime classification and static control flow.

Use automatic GPU selection plus RequireHardwareAcceleratedVideoDecoder on this
built-in topology. Do not fake an external/slotted GPU merely to satisfy the
optional ID filter. No Apple XPC binary patch or global DYLD environment change
was needed for the demonstrated HEVC fix.
