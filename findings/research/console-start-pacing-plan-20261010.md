# Candidate440: test completion-relative GUI refresh cost

Only full-field4K performance active; all other roadmap work on hold. Keep host
viewer normal1440×900/GDK1, no automatic input grab/USB redirection. Host awake.

439 lossless compression reduced traffic but did not materially close delivery
gap. Traced Retina full-field23.47/23.50 client IDs/s versus43–44 server commands/s;
rawX11 profiling27.04; rawWayland24.39, sequential activity not isolated. Full RGB
static color and high-entropy image exactly match QEMU; moving60 not qualified.

Source QEMU gui_update records last_update after dpy_refresh and schedules that
completion+interval.16ms+4.6ms work fits observed~49refresh/s; localized16+1.4ms
fits~58. This correspondence is a hypothesis, not causal client-delivery proof.

Research patch sets a per-listener flag only for nongl explicitSPICE60 and uses
17ms instead of16, keeping at most58.82Hz for this millisecond discriminator.
Fastest listener opts into callback-start-relative scheduling; unchanged default
listeners retain completion-relative behavior. Expired ticks are skipped to a
future deadline, with overflow saturation. Outside-callback interval shortening
also clamps future ticks while opted-in pacing is active; zero means default.
The compiled helper passes randomized brute-force and boundary/overflow tests.

Preserve refreshing guard and final listener-minimum calculation after callbacks,
so an interval change during callback affects the next tick. Shared timer means
other listeners can affect cadence; this run requires the existing sole relevant
SPICE listener/noVNC/SDL profile. Do not claim generic multi-listener qualification.

Next compare same rawOFF/sourceRetina60 and normalX11 viewer, with4s bounded startup
settling and strict post-ready geometry checks. Enable existing pipeline traces
for refresh/create/dequeue/client phase attribution. Increased polling alone does
not prove higher client delivery. Retain separate capture and cleanup outcomes.
No driver/capture app/source fixture changes. Same439 SPICE library, QEMU437 base
plus this patch. Build in device-free/capability-dropped/networkless container.

Exact60 remains the goal: if useful, higher-resolution/fractional scheduling must
follow.17ms is not a substitute completion criterion or a60Hz qualification. No
hardware result or new feature publication yet; candidate439 has authorizing
recovery receipt. Defaults/other modes remain unqualified outside prior scope.

Review scope: arithmetic tests do not prove listener integration. Outside-callback
zero-interval reset with mixed listeners does not recompute all minima; that case
remains unqualified and is not present in the fixed sole-SPICE experiment.

## Completed candidate440: scheduling changes polling, not delivery

Run7735f915a55c10b180a6960fe8aeb5b4, MODE2335, MetalprobePASS; build9cfef702a0db4472b509e1c69f2f8a63,
sourceGPUd1deade... unchanged.1555hosttests8skip. Actual scale2 Retina source60,
normal1440×900/GDK1 X11, same sealed presenter and439SPICE, explicitOFF channel
preference,4s startup settle and strict subsequent geometry checks.100sec test
4364unique,13startup-invalid,0post-start,1duplicate; short final phase excluded.

Fullfield phase interiors refresh58.07/58.13, create/dequeue44.26/44.10, client
21.94/21.88 IDs/s. Localized55.58–56.26, queuebusy0. Thus start-relative scheduling
worked at polling layer, but did not close downstream delivery gap. It rejects
completion-relative timer as sufficient/dominant fix for this configuration; does
not establish regression versus prior sequential traced runs. No exact60 claim.

Primary source audit: pixman0.46.4 sse2_blt4676 andcopy_area4802 preserve raw4bytes;
no X normalization in that observed path. SPICE0.16 display-channel.cpp482–499
can replace pending opaque same-region draws, removing unsent client pipe items
376–385. Dequeue is not marshalling/display. Historical380 software measured this
and large Cairo scaling cost; current native renderer remains next discriminator.

Guest-requested exit/natural captures/private terminal verified, stopped-container
inspection reconciliation unavailable/mismatched; recoveryauthorizes=true.
Artifacts c440-fourk-a-pipeline-analysis.json withraw hashes, source/cadence/trace,
shared-clock proof and~/macos-vm/run/candidate-440-results/. No release.
