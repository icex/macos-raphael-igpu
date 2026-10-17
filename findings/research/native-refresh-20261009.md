# Candidate345: faster native console, zombie exit-receipt race

Run `e5c19e2555990ca2df1d9ac171c73fac`, metal-190, build1.0.345,
MODE2#285 on bootba51b3c6. Native Metal, WindowServer ownership and exact paused
refresh admission pass. The actual virt-manager window renders both selected
modes, and display-awake assertions are verified. The independent software
refresh A/B and image provenance are linked in the [plan](native-refresh-plan-20261009.md).

## Measured output

Same30-second in-process full-pixbuf sampler and60-second AppKit token fixture
as342, fresh nonces, one actual manager connection per mode:

| Metric | Native1920×1080 | HiDPI3840×2160 |
|---|---:|---:|
| Distinct valid sampled tokens |1500|676|
| Sampled tokens/s |49.993|22.529|
| Candidate342 reference |29.823|18.496|
| Invalid samples after first valid |35|113|
| Median sample cost |2.257ms|5.330ms|
| Median distinct-token gap |16.058ms|32.122ms|
|95th-percentile gap |48.170ms|96.308ms|
| Skipped draw IDs |99|663|
| Completed60-second AppKit draws |3309|2885|

Both fixtures finish and the normal desktop returns (screenshot inspected).
The measured rate improves, especially at1080p, but does not establish60Hz
end-to-end delivery, GPU fps, host scanout or absolute latency. This native
comparison includes a rebuilt QEMU binary; the software A/B isolates the refresh
patch more narrowly. Full-pixbuf copying is measurable observer overhead.

Invalid samples increase relative to342. The separate serialized software
producer also yields intermediate tokens because SPICE sends multiple regions;
a diagnostic single-rectangle update removes those software invalid samples.
That diagnostic patch is not in345. These observations do not establish native
GPU corruption or rule out concurrent guest framebuffer-copy races. A checked
small-region observer is the next independent measurement control.

## Capture and teardown

Closing the viewer leaves the same CID running. The hardware owner requests
harness shutdown. Capture is valid CORE_PROBE_PASS, earliest_failure=null;
outer shutdown is exited-after-guest-request. GPU recovery is recovered and
authorizes_launch=true. No reboot or rebind; host remains awake.

**Native terminal.json is absent.** Both EOF handlers refuse the original QEMU
PID113/start identity because it is still present in process stateZ (zombie),
then record immediate-stop at about0.432seconds. This is a different diagnosed
boundary from the unused SSH privilege-transition process fixed in343.
Candidate343's one successful natural terminal receipt remains valid evidence,
but it did not qualify all native shutdown timings. Do not report345 as a clean
native-controller exit. Next inspect Linux exit ordering and prove any narrowly
accepted completed-process state in software before another native run.

## Reproduction and delivery boundary

Full host suite:1157 tests pass,3 skipped. Kext and manifest in this candidate
match the tested345 build. The experiment image replaces only QEMU; driver source
is unchanged from343. Default `experiments/pins.json` is restored to the stock
image for delivery. To select this experimental image explicitly:

```sh
python3 -B tools/cycle.py --candidate 345 --card metal-190 --pins experiments/pins-spice60.json
```

The original run used the same image while it was temporarily selected in this
candidate's default pins atf2725ec; manifest/image hashes preserve that identity.
The stock-QEMU343 milestone is already ondev29b462e with green hosted tests and
macOS build. Candidate345 remains local pending lifecycle follow-up.
[Raw artifact paths and hashes](native-refresh-evidence-20261009.json).
