# Candidate366: persistence and source cadence

Run `4e1ee174e75b04e804e28d3efd614d9e`, metal-203, build1.0.366/65c6d6549d144f319d2a7e84f905d202,
sourcefcfea4e, runHEAD61b3519, MODE2#299, same bootba51b3c6.

The existing installed console app automatically started after the next guest boot.
Its presenter hash remained6a2ecdd51cec93af1961b5402f324aab85a4ee6cec9d761d27c5fc036f1596cf;
fresh3840x2160 capture began without another TCC permission change. Awake assertions
were present. Actual virt-manager shows a correct desktop after the tests (final
screenshot). This qualifies existing-user next-guest-boot persistence, not host boot,
fresh-user consent or console-only first setup. Audio/input were not rerun.

## Timing experiment

Native Appleclang17 compilation of the new source fixture succeeded (six deprecated
CVDisplayLink warnings). Native and HiDPI warmups decoded moving tokens. The full
ABBA comparison holds1080HiDPI, installed presenter, explicit QEMU full-refresh ON,
SPICE60 and actual manager ROI observer constant. Each source runs70s; the observer
runs35s after10s source warmup. Analysis excludes first5s of observation and uses30s.
No other agent ran heavy tests during measurement; user host activity is not isolated.

| Case | Source draw calls/s | Valid unique manager IDs/s | Invalid/samples |
|---|---:|---:|---:|
| baseline-a | 33.063 | 23.633 | 336/1816 |
| prerendered-b | 60.000 | 35.300 | 442/1550 |
| prerendered-c | 60.001 | 24.900 | 959/1756 |
| baseline-d | 53.647 | 25.967 | 826/1784 |

Prerendered/CVDisplayLink draws reach60 calls/s, but do not establish completed
WindowServer/GPU/composition frames. Manager measurements are rawbuffer sampling
lower bounds, not host scanout or GPU FPS. Repeats vary substantially; neither
60Hz output nor a stable speedup is qualified. CRC/torn-cell failures remain.
Retained presenter tail timing windows are not clock-aligned to the analyzed interval.

Next discriminator: validate nonce/CRC/two-copy regions in the actual readonly
ScreenCaptureKit buffer before VRAM writes. Valid source plus invalid manager samples
would narrow suspicion downstream; source errors would place a fault no later than
capture. Neither alone identifies a specific stage or proves full-frame atomicity.

## Capture and cleanup

CORE_PROBE_PASS, earliest_failure=null. Closing the owned manager left the exact
VM alive. Harness stop-requested produced private terminal guest-shutdown with
process_exited=true. Both capture exits deferred and completed natural-container-exit
in~0.451s; shutdown_event_wait=false and completed_original_zombie=false. Critical
recv-reset remains distinct from console cleanEOF. Recovery recovered and
 authorizes_launch=true. Cycle stopped; host sleep:idle blocker retained. No reboot
or vfio-to-amdgpu cycle. This does not repeat364's pending-worker event-wait branch.

1264 host tests passed,8skip before exposure. Source fixture focused tests passed.
[Artifact hashes](console-cadence-native-evidence-20261009.json) retain raw analysis,
source/manager samples, identities, screenshot and terminal/recovery evidence.
