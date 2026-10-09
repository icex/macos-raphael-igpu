# Live status — 2026-10-09

## Candidate379: event measurements localize slowdown; rare HiDPI errors remain

Run13d30f59db11f72dea720cee7f5f84fd,metal208,1.0.379,MODE2#304,
bootba51b3c6. Same374 changed-bbox image and installed370 presenter/consent.
Three110s mixed fixtures;300s synchronous actual-manager ROI observation.
HiDPI3723 valid/1 post-start invalid; native5285/0; traced HiDPI3736/2.
Startup invalids1/1/10 retained separately. This is not corruption-free qualification.
First30s source window:1566 valid,9 unavailable,0 decoded errors; none of the
three malformed manager observations covered by that source diagnostic.
Native observer stalled~983ms before ROI decoding; cause unresolved.

Traced full-field interiors: QEMU publications39.39/37.94 per second,
bitmap-creation entries39.39/38.01, client invalidations14.40/14.54.
Localized~50–51 creation/client events match. The main measured gap is after
bitmap-creation entry; pre-create queue gating and timer sampling alone do not
explain it. Trace restored disabled. Next: software-only SPICE server
consumption/coalescing/send measurements; do not disable backpressure blindly.

Readable ordinary desktop screenshot; default stereo USB/QEMU/Pulse capture and
independent route restoration pass. BAR0 positive mapping and retired ARM/staging
regrant refusal pass; original agent and awake3840x2160 capture restored.
Input not rerun; endpoint audibility/A-V sync unqualified.
CORE_PROBE_PASS/earliest_failure=null; private guest-shutdown/process_exited=true.
Both captures natural-container-exit(~0.397s), shutdown_event_wait=false;
console clean EOF, critical recv-reset retained. Recovery recovered,
authorizes_launch=true. Cycle stopped; host awake,vfio-pci/on.
374 forced-stop D-state race remains unresolved;377 diagnostics not exercised.

1311 host tests pass,8skip; exact build/identity/dry-run pass. Delivery suite
1311pass/8skip; current docs and tested379 kext delivered to dev5cee25d. Remote
ref verified; hosted37959795782 test/build green, release skipped. Main unchanged. Every future push requires exact-commit
hosted CI test/build success and applicable release/deployment checks.
[Evidence](findings/research/console-event-native-20261009.md) ·
[Hashes](findings/research/console-event-native-evidence-20261009.json).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-381-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
