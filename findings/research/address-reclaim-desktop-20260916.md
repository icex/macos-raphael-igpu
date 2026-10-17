# Candidate 280: address recycling, native reclamation and desktop coverage

Run `dd5c30a35fea14f9be511dee92ff85be`, MODE2 #159, nineteenth exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. Driver and QEMU unchanged from prior 280
qualifications. [Exact artifact/source hashes](address-reclaim-desktop-evidence-20260916.json).

## Functional results

- **Buffer/address workload:** 512 measured rounds plus three warmups; 48 MiB live
  resources; 2,147,483,648 measured 32-bit values, zero mismatches. Including upload,
  compilation and relay, elapsed time was 525.74 seconds. Every release settled at
  exactly 544,768 bytes, from a 50,974,720-byte peak. No live address overlap.
  All 6,144 measured assignments reused a previously observed 4 MiB address range:
  4,096 managed and 2,048 private. Across warmup/measured observations, managed
  assignments used 12 distinct ranges, private assignments 10 (ranges overlap
  between storage classes across different lifetimes). This proves recycling of
  released buffer addresses under correct subsequent GPU work. Cached mappings
  may persist; this is not proof of page-table invalidation or every GPU-VA release.
- **Untracked-resource synchronization:** explicit upload-blit -> compute -> readback
  fences passed 128 rounds / 134,217,728 values. Both private resources reported
  untracked hazard mode. One queue, three encoders, managed CPU synchronization;
  interprocess event sharing and all render/depth hazards remain outside scope.
- **Larger buffers:** 192 MiB live resources; four measured rounds plus one warmup;
  67,108,864 measured values, zero mismatches; exact allocation return. Native
  tracing resolves the formerly suspicious allocation messages into successful
  reclaim/retry sequences in this workload. [Caller and live evidence](allocation-retry-analysis-20260916.md).
- **Native composition:** three minutes of animated background colors and four
  NSVisualEffectView materials, with repeated window movement/resizing. Event-loop
  exit was clean (1,904 event ticks; these are not frame completions). Four raw RFB
  captures were visually inspected: early, 60, 120 and 165 seconds; all unobscured
  and clean. The 20-second precursor duration was corrected before this execution.
- **Safari:** local CSS blur/transparency/transforms and automatic scrolling. Raw
  captures at 15, 60 and 125 seconds were clean. The last shows 3,601 animation
  callbacks / 120 seconds; callback count is not presented-frame timing. A later
  raw capture after larger-buffer pressure remained clean. These are bounded
  sampled visual observations, not a continuous pixel oracle or browser conformance.
- **PerfPowerServices:** 0.0% CPU, latest 1.04 seconds cumulative CPU. This is the
  sixth fresh guest boot on the same host boot with corrected QEMU.

Global statistics sampled during active Safari animation showed only 5,226,496
free VRAM bytes, roughly 269 MB in-use video memory, roughly 95 MB reusable video
cache and zero non-reusable orphan counters. This is an active workload sample,
not a like-for-like idle baseline or a new reclamation comparison.

## Capture, cleanup and overall result

Core probe passed; identity and critical capture valid. Terminal snapshot 18 has
372 records, zero dropped/truncated. Shutdown was `exited-after-guest-request`.
Schema 6 recovery is `recovered`, authorizes another launch; host fault list empty.
Overall **CORE_PROBE_PASS**. Four candidate 280 lifecycle runs have now completed
cleanly on this one host boot. Host suite: 938 tests OK, three skipped.

Full desktop/physical display acceptance, independent host boots, guest crash and
QEMU closure remain distinct gates. The next work is an explicitly recorded,
supervisor-owned QEMU closure; its result must not be called a clean guest shutdown.
