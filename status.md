# Live status — 2026-10-10 — focus only on4K QEMU performance

User priority: full-screen4K guest performance; all native-framebuffer/120Hz/5K,
clipboard/USB and other roadmap work is on hold. Keep the QEMU viewer in a normal
host window; no host fullscreen or automatic input capture while user tests other
applications. Performance tests use a full-field4K guest workload in that window.

435 run0132fd022f53f29a9ce1d0f3c7f687b8 restored original GPU dependencies and
passed its identity-bound Metal probe. Active1920×1080 logical/3840×2160 backing
was verified; capture app/seal unchanged after external launcher-guard install.
Standalone driver load was refused by OSapproval; it is not qualified or enabled,
and that investigation is halted. IOGraphicsFamily599 is loaded after desktopboot.

The guest subsequently emitted poweroff/systemWillShutdown before the planned
interactive deadline; original cause is not established. Capture hooks immediate-
stopped, wrapperINVALID/serialcapture-not-running; do notcallclean shutdown.
Recovery returned recovered, authorizes_launch=true. No GPU VM is running; host
awake, vfio-pci/powercontrolon. Receipts ~/macos-vm/run/candidate-435-results/.

The requested matched-fullscreen measurement did not complete. X11 sees one
combined3840×1080/GDK2 monitor (7680×2160 physical), Wayland onecombined5120×1440/
GDK2; exact1920×1080 viewport checks refused. No performance numbers from those
attempts. Owned fullscreen viewers stopped; next cycle uses only a normal window.

History:397/399/402/4304K mixed workloads scaled into1440×900 show full-field
about25–27 decodedIDs/s and localizedabout49–60; no comparable newregression
established.381 matchedphysical4K viewport observed34.5–34.9 full-field vs14.4
scaled, but olderQEMU/transport differs. Fresh windowed control+stage attribution
is next. Countsource/capture/publication/client separately, retain integrity limits.
1538hosttests passed before435; current publisheddev e240b38ae1d878d429369e41ab5b1179108c2a26
has green hostedCI38040411149. No new feature publication. Main unchanged.
