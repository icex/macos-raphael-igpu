# Live status — candidate 277 HEVC hardware decoding works

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, six exposures complete.
Run `532ac6d9eefc560e06f6df973245fd67`, MODE2 #140: CORE_PROBE_PASS,
guest-requested exit, recovered. GPU left vfio-pci with power/control=on.

Fix: exact marked Raphael PCI IOService S30 -> GFX0 before HW engine init.
276's raw lookup showed actual S30 excluded from AppleGVA's name filter; its
unrelated IOResources display node has no properties. 277 makes Apple's recursive
lookup find the existing complete capability dictionary. No XPC injection.

Evidence in candidate-277-results:
- capability-lookup-output.txt: GFX0 has HEVC properties via recursive child search.
- hevc-name-fix-output.txt: auto hardware-required HEVC decodes 3/3, hardware=true,
  max luma error 0. Explicit RequiredDecoderGPURegistryID still -12906.
- hevc-swstream-600-720-output.txt: 600/600 unique software-encoded HEVC frames
  hardware-decoded, 535095000 luma values, zero error.
- hevc-hwstream-600-1080-output.txt: 600/600 unique HEVC hardware encode/decode,
  1217295000 luma values, max error 1.
- h264-hwstream-600-1080-output.txt: 600/600 unique hardware encode/decode, max error 1.
- hevc-recreate-600-720-output.txt: 600/600 after H.264 teardown, zero error.
- serial.txt: HEVC decode codec=4/channel=8/encode=0; matching encoder and H.264
  contexts. All standalone sustained probes exit 0.
937 host tests pass (3 skipped).

User requested repeated testing. Extend allowance by one exposure (seventh total)
on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, same candidate binary, fresh guest
boot and MODE2, manual-reuse/ack-risk, 6000s cap, all existing abort/cleanup gates.
Test longer HEVC stream and software-produced 1080p on a fresh guest.

Explicit-ID selection: static VideoToolbox registration code only creates per-GPU
decoder registry entries for slotted/external devices; built-in retains the global
entry. Verify runtime classification/list before declaring this expected behavior.

Limits: 8-bit 4:2:0 tested; Main10, arbitrary content, full desktop/display and
crash-recovery repeatability unqualified. No main merge or push.
