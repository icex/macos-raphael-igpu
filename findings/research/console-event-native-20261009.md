# Candidate379: event observation locates the next console bottleneck

Run `13d30f59db11f72dea720cee7f5f84fd`, metal208, version1.0.379,
MODE2#304, boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Build `c3e4e8d6f3be4fe7b2d94fb49b52adb6` was built cleanly from
`ce106d9e72b92fb8a91c506c40f98990db7d3e76`; admitted coordinator/card HEAD
`c964bde354b8132f599c98911bf37cc9968fb7ca`. Executable SHA256:
`df0079ea0adde6d818b744cccd984e18f65d7322fc67dc234b3d4bd92606ef7b`.
Same changed-bbox QEMU image as374/376:
`sha256:96748992f5baee3b6884bc68445ceed04b6ebe2b00c6c9cbe360ad835ec2e890`.
Guest24G830, existing presenter/consent, explicit SPICE60/full-refresh/snapshot;
actual virt-manager5.1.0, spice-gtk0.42-5, server package **spice0.16.0-2**.
The1311-test host suite passed with8 skips; deep identities and dry-run passed.

## Observation and integrity

Three finite110-second mixed-motion fixtures alternate localized tokens and a
smooth low-contrast changing background. Each has a100-second actual-manager
window. Candidate378's event observer decodes synchronously after each existing
SPICE channel invalidation, avoiding timer-only sampling omissions; it opens no
second SPICE connection. Callback/rectangle records, QEMU diagnostic counters
and source DRAW phase transitions are retained. DRAW means completed drawing
calls, not scanout. Counts below include distinct decoded IDs, not GPU FPS.

| Case | Valid token samples | Unique IDs | Startup invalid | Post-start invalid |
|---|---:|---:|---:|---:|
|HiDPI event observer|3723|3722|1|1|
|Native1080p event observer|5285|5285|1|0|
|HiDPI event observer plus QXL trace|3736|3736|10|2|

All **three post-start errors remain failures of token validation**, rather than
being discarded as startup or hidden by the guarded rate analysis:

- First HiDPI: host76920.945600642, valid neighboring DRAW IDs2331→2335,
  `missing token border; checksum mismatch`.
- Traced HiDPI: host77613.225223025, IDs71→76, border/checksum mismatch.
- Traced HiDPI: host77694.201404260, IDs4923→4926, border/torn-cell error.

The guarded interior tables happen to exclude these near-boundary errors. They
must not be summarized as an error-free case or whole-frame atomicity proof.
Event observation may reveal rare errors the earlier timer missed; changed
observation does not by itself establish a driver regression or error origin.

The first HiDPI source diagnostic completed its30-second window over IDs1–1792:
1575 processed samples =1566 decoded valid +9 unavailable (`error_8`),1564 unique,
2 duplicates, zero CRC/torn errors. Its rare manager error is outside that ID
span. Native and third-case presenter logs contain the earlier source summary;
it does not validate those fresh nonces or the entire110-second workload.
Processed source checks exclude busy-dropped/upstream-uncaptured frames and do
not establish stability after checking or every full-frame pixel.

## Stage rates and the new discriminator

Rates use identical host intervals bounded by eligible counter observations,
inside2-second guards inferred from valid manager IDs and actual source phase
records. Guest and host clocks are not subtracted. Source DRAW cadence remained
approximately60/s. Ranges below summarize separate complete interior phases;
partial final phases are excluded.

| Case / damage | Snapshot ACK/s | QEMU published/s | Client unique IDs/s |
|---|---:|---:|---:|
|First HiDPI localized|55.42–57.18|48.96–51.19|49.03–51.19|
|First HiDPI changing background|41.09–42.09|37.49–38.08|14.34|
|Native localized|57.59–58.01|57.59–58.08|57.66–58.01|
|Native changing background|57.86–57.97|57.44–57.73|42.78–48.13|
|Traced HiDPI localized|56.44–56.91|49.78–51.38|49.71–51.31|
|Traced HiDPI changing background|42.01–42.99|37.94–39.39|14.40–14.54|

ACK means accepted immutable host snapshot; published counts QEMU surface
replacement/update calls, not server command consumption or client delivery.
Synchronous full-field client callbacks remain around14/s despite37–39 QEMU
publications/s, so timer scheduling alone does not explain the gap.

A source audit found a possible earlier coalescing stage: QEMU's SPICE refresh
consumes a pending snapshot before checking whether its QXL update queue is empty.
That was a hypothesis, tested in the third case by enabling only the existing
`qemu_spice_create_update` trace event. Exact identity-bound libvirt QMP preserved
the prior disabled state, and restored it after125 seconds.5038 strict trace
records were extracted from virtlogd's regular backing log; the QEMU stderr pipe
was not read. Startup argv/XML and all unmatched lines were never exported.

| Traced full-field phase | QEMU published/s | QXL creation-entry/s | Conservative trace rate bounds | Client invalidations/s |
|---|---:|---:|---:|---:|
|1|39.392|39.392|39.125–39.659|14.397|
|3|37.943|38.010|37.676–38.210|14.537|

Localized QXL creation and client events both track about50/s. Full-field
rectangles are3840×2112 (8,110,080 pixels), leaving the unchanged top48 pixels;
localized means are about27–29 thousand pixels. Trace UTC timestamps were aligned
to host monotonic using before/after QMP clock pairs, with a conservative~105ms
wide calibration envelope and observed offset spread0.24µs. Unobserved clock
steps remain a limit. Trace creation is emitted **before** allocation/copy/enqueue;
it is not a completion or server-consumption acknowledgement.

**Conclusion:** in this run the large publication-to-client gap is downstream of
QXL creation entry. The QEMU queue gate is not its dominant observed cause.
This does not isolate spice-server alone: bitmap creation completion, server
command consumption/redundancy, transport and client processing remain distinct
stages. No optimization or transport change was made from this hypothesis.

Pinned QEMU10.1.2 explicitly sets streaming video OFF when the option is absent;
adding `streaming-video=off` would restate current initialization. Absence of
stream messages without SPICE_DEBUG is not independent evidence of no streams.
No rare token error is attributed to video compression or a specific stage.

## Observer costs and limitations

Guarded HiDPI callbacks average about0.74–0.91ms; native averages about0.57–0.64ms.
The native stream has a separate **983.440ms callback stall** at index4097:
raw invalidation begins77240.179355597, decoder entry77241.161919051, and measured
ROI decode takes only0.832ms. The long gap precedes decoder entry and may involve
logging/flush or scheduling; it is not attributed to GPU, source copying or ROI
copy cost. Whole-window native heartbeat gap is987.5ms and stale bound1.006s.
First/traced HiDPI stale bounds are82.2/104.1ms; heartbeat gaps316.0/283.9ms.

Native final callback5287 was in progress when the deadline summary was emitted;
5286 completed callback costs were recorded. This is explicit accounting, not a
fabricated final duration. Other cases have all invalidation completions.
Widget redraw counts3710/5134/3732 are redraws, not frames/scanout. Added synchronous
Python/ROI/logging, counter polling and tracing can reduce throughput. No stable
60Hz, full-frame integrity or absolute-latency claim follows from these tests.

## Audio, retirement and normal desktop

Default application `afplay` stereo delivery through guest USB/QEMU/Pulse passes
on the first attempt:
left~997.14Hz, right~1498.57Hz, silent opposite channels and simultaneous stereo
phases pass the objective analyzer. WAV SHA256
`26a0a67caf2ad5bac2157353c3a5aeeae3e98979ce2cb8683da988adb48db130`.
Independent inspection confirms original sink, volume, mute and defaults restored,
and the owned capture module removed. This is not endpoint audibility or physical
HDMI audio qualification; physical330 remains its separate baseline.

After orderly snapshot-owner retirement, the negative bridge probe confirms
legacy BAR0 mapping remains available while ARM/staging regrant are denied. The
original agent was restored (SHA256
`b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82`), ordinary
3840×2160 capture restarted, and display-awake assertions remained active.
`c379-desktop-manager.png` visibly contains a readable macOS desktop in the real
manager window. Exact VM identity was verified alive after closing that owned
viewer. No new input or fresh-user setup qualification is claimed.

## Shutdown and delivery

Final receipts were independently read after root completed cleanup:
`CORE_PROBE_PASS`, earliest_failure=null; private terminal reason=guest-shutdown,
process_exited=true; outer shutdown=exited-after-guest-request. Both capture hooks
observed natural-container-exit with deferred=true in0.39685/0.39687 seconds.
For this run **shutdown_event_wait=false** and completed_original_zombie=false;
this is not a repeat of376's guest-event pending-worker wait branch. Console
transport ended with clean EOF; critical transport ended with recv-reset. The
critical reset is retained as its actual transport result, not renamed clean EOF.
GPU recovery status=recovered, authorizes_launch=true. Final host observation
retains the same boot, vfio-pci binding, power/control=on and active awake service.
The earlier374 forced-stop D-state race remains outside this orderly-shutdown
qualification. Input was not rerun. This research draft does not itself claim
dev/main delivery; root owns milestone integration.

Raw paths, analysis scripts, build/run identities and hashes are in
[the evidence manifest](console-event-native-evidence-20261009.json).
