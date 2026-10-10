# Live status — 2026-10-10 — graphics dependency blocks early GPU plugin load

Candidate434 run358fb6dbb31ef9c2bb1e26aee5995fb2 isolated433's added dependency:
exact last-working432 GPU source, no native framebuffer class/personality/imports,
but IOGraphicsFamily2.0.0 still in plugin Info.plist. macOS repeatedly reports
"library kext com.apple.iokit.IOGraphicsFamily not found" and refuses RaphaelGPU
with0xdc00800e. No build marker or Metal result. The new class is unnecessary to
reproduce a loading failure. This does not establish that433's later panic had
an identical full cause; runtime1.0.3/8192-byte metadata mismatch remains open.

Function: no accelerated desktop qualification. Capture: INVALID/identity_or_route_missing.
Stop: exact supervisor forced stop; wrapper reportsalready-stopped, not cleanshutdown.
Normal recovery lacks critical producer readiness. Supported schema9 stopped/noqueue
inspection+execute returned recovered, authorizes_launch=true, no host faults.
Receipt: ~/macos-vm/run/c434-noqueue-recovery.json; runresults:
~/macos-vm/run/candidate-434-results/. Host awake, GPU vfio-pci/powercontrolon;
no GPU VM running.1537hosttests passed (8 skipped) before the run.

Next: restore original GPU-plugin dependency set; package native framebuffer as a
separate IOKit kext with its own identity and loading evidence. Inspect guest
IOGraphics/KC state after baselineprobe completion before choosing runtime install
or boot injection. Install the external launcher ownership guard before enabling
native framebuffer matching. Preserve full prototype on433; current434 is only
an isolation branch. Native120VBL, dynamic Retina resize and5K remain unqualified.

Offline audit: staged433 archive matches, one OCAdd entry; all88 IOFramebuffer
imports exist in24G830 KDK externalsymbols. SDK base IOFramebuffer size0x1d0
matches actual24G830 MetaClass size, but this is not full vtable/relocation proof.
432 accepted native120 EDID while CVDisplayLink remained30Hz.430 baseline has
correct4K Retina picture, source60/clientabout60localized27fullfield.
Published dev e240b38ae1d878d429369e41ab5b1179108c2a26 retains working clipboard/
GUI USB and1.0.428; hostedCI38040411149 passed. Main861ba5e unchanged. No new
milestone publication; virtualBox deferred.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-435-results`
- Verdict: `INVALID`
- Boundary: `None`
