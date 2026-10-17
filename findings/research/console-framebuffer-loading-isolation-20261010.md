# Candidate434: isolate the graphics dependency

433 failed at OSKext::start before its build marker. Its staged/archive kmod is
1.0.433, while panic metadata reports as.rgpu.RaphaelGPU1.0.3/8192bytes. The
non-present instruction fetch is below that listed module address. There is no
evidence yet that a framebuffer method executed or that text was rejected by NX.

Offline audit confirms one enabled OpenCore RaphaelGPU entry after Lilu and
byte-identical staged/archive executable SHA256
25b8c6201ee73f7506a14a4234c11736d0c4db7c6af56890f4b3acc426ef198f.
All88 new IOFramebuffer import names are externally defined in actual24G830 KDK
IOGraphicsFamily. This does not prove OpenCore resolved or relocated them correctly.
The tiny runtime identity may involve cached/prelinked metadata; that is unproven.

434 preserves the full native framebuffer prototype on branch433 and removes its
class/personality only in this comparison. Actual GPU source digest returns to
the last working432 digest d1deadebe29f9527a63404eba136085e644b482e833c47e9d10fb22034ddc843.
The added com.apple.iokit.IOGraphicsFamily2.0.0 dependency remains. Required
observations and host/capture/recovery checks are unchanged. Native-aware external
launcher code is retained but no native framebuffer is present to suppress helpers.

If the same startup/identity failure repeats, the new class is unnecessary to
reproduce it; investigate dependency/prelink metadata before changing native code.
If baseline boots, investigate new-class registration/import relocation and its
ABI against24G830. Neither outcome qualifies the native120 display path.

Root owns hardware. Wait for identity-bound probe completion before any gx helper
command. Only after a working baseline may the external launcher guard be installed,
without signing or changing the capture app. Preserve every shutdown/recovery receipt.

Result: run358fb6dbb31ef9c2bb1e26aee5995fb2 repeatedly failed dependency resolution:
`library kext com.apple.iokit.IOGraphicsFamily not found`, error0xdc00800e. No new
class imports are needed for this failure. Native code cannot be qualified until
the main GPU plugin again loads. Restore its original dependencies and isolate
the framebuffer in a distinct IOKit bundle. The433 later panic/runtime metadata
mismatch is not fully explained by this comparison.

Exact supervisor stop preserved runner receipts; wrapper INVALID, no core probe.
Normal recovery lacked producer readiness; schema9 stopped/noqueue recovery
authorized same-boot reuse with no host faults. Tests1537 passed/8 skipped.
Evidence: `console-framebuffer-dependency-evidence-20261010.json`.
