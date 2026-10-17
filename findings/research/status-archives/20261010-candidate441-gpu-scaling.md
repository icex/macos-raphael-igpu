# Live status — 2026-10-10 — 441 host GPU scaling gain

Only4K performance active. All120/5K/native-framebuffer/other roadmap work on hold.
Host viewer normal, no fullscreen/grabs/automaticUSB. Host sleep:idle blocker retained.
No VM running; original441 runner terminal0, guest testjobs removed and viewers closed.

441/metal235 run19088a4a33e92ee4b5653807671d66be CORE_PROBE_PASS, MODE2336,
build1ce9c016abef451ba4252674e3a4693d; unchanged GPU source d1deade....
Image085d8ac... is439 matching-versionSPICE with rawOFF; rejected440 pacing reverted.
Private spice-gtk0.42 raw-primary GtkGLArea on host RX9070XT hardwareGL, GPU linear
scaling of decodedCPU primary, defaultCairo unchanged. Actual loaded maps verified.

Same-boot sequential GLvsCairo at actual1920logical/3840backing scale2/source~60,
normal1440x900/GDK1: full-field phaseinteriors GL37.74/41.80 vsCairo23.73/23.85
unique decodedIDs/s; localized GL55.74/56.22 vsCairo56.59/56.26. Meaningful gain,
not sustained4K60, displayed-frameFPS, whole-frame motion integrity or root-cause proof.
Both100s observers startedlate and outlasted110s sources:32/36 trailingmissingborder
samples retained; zero invalid inside compared source intervals. Standardpipeline
analyzer correctly refuses originalrecords; scopedphaseanalysis preserves that limit.
Hostactivity uncontrolled; need counterbalancedrepeat with coordinatedsource/start.

Synthetic paddedstride1:1 RGB exact, scaled bilinear maxerror1, blackletterbox.
Native staticCPU3840x2160 to GLFBO1280x800 matches bilinear RGB exactly; viewedpattern
has correctorientation/colors. Filtering equivalence to CairoGOOD, text quality,
moving-frameintegrity, input/cursor/crop/resize/context/fallback lifecycle remain open.
No smaller source or nearestfilter substituted; GPU renderer remains opt-in research.

Shutdown exited-after-guest-request; natural console/critical captures, private terminal
verified; stopped-container inspection unavailable/mismatched reconciliation warning
retained. Recovery recovered, authorizes_launch=true.1555hosttests8skip and13clienttests
passed beforelaunch. Ship checked-in428 bundle unchanged; no newmain publication.

Evidence: findings/research/console-raw-gpu-scaling-20261010.md and evidenceJSON;
~/macos-vm/run/candidate-441-results/, c441-native-phase-comparison.json,
c441-native-gl-pixels-check.json, c441-fourk-{a,b}-* and manager maps.
Next: qualify/repeat GPU scaling at full4K with source-overlap lifetime, filteringquality
and rendered-frame integrity; then remove remaining delivery ceiling toward sustained60.
User no-progress pause condition was not triggered by441 measured gain. Goal remainsactive.
