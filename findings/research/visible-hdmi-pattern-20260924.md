# First physically visible HDMI pattern — 2026-09-24

Candidate318 attempt-pattern, run338d9498eb9e7e029f0f73570450b41f,
source19f6e6e, build26a2d58b4abf4df490c83a89ceb2cfd3, metal166, MODE2#245.

The user reported "I saw some patterns now!", then "now they are more fuzzy but
same pattern" and "it is interleaved now". This is physical output evidence but
not pixel correctness or a macOS desktop. No physical screenshot was captured.

The opt-in rgpudcnpattern=1 replaces native OPP0 DPG_CONTROL0 (video mode) with
661001: enable, RGB color squares, VESA range,8-bit generator, HRES/VRES6. Other
native blanking requests remain intact. Linux opp2_set_disp_pattern_generator is
the source for these fields. Active readback verified661001 and1920x1080 dimensions.
HDMI enabled, native1080p60, scrambling off, AVMUTE0. Firmware reload passed3
queries;14 type128 commands consumed. DRAM policy1032, DCHVM active/prefetch-done.
Framebuffer SURFACE_INUSE0 remains; pattern bypasses pixel fetch.

Before observation, launchd-owned caffeinate supplied UserIsActive1 and
PreventUserIdleDisplaySleep1. New tools/guest-display-awake.sh verifies both and
is documented as mandatory before physical observations. Native1080p60 selection
was read back via CoreGraphics and the existing QEMU MMIO mapping.

Core probe passed. Final verdictCORE_PROBE_PASS; complete critical capture.
Stopped through stop-requested; exited-after-guest-request and recovered with
authorizes_launch=true. Run artifacts under candidate-318-attempt-pattern-results.
Hashes and live snapshots: visible-hdmi-pattern-evidence-20260924.json.

Earlier318 run6f4c3b2d2bb525c6c622baaa9560eaa0 panicked at corecrypto FIPS POST,
before Raphael. Exact-supervision shutdown forced closure; runner completed its
receipts. Separate schema9 noqueue recovery authorized this same-boot retry.

Prior316 selected native1080p120 but user saw black.317 held display awake and
selected1080p120 then1080p60 with scrambling off; user still saw black. Preventing
forced SR permission during active scanout therefore is not a sufficient fix.
316's color-only diagnostic did not force the generator on after unblank, so its
negative observation did not test downstream output conclusively.

Next: correct framebuffer fetch, then verify real desktop pixels and formatting.
Reported fuzziness/interleaving remains unqualified; do not extrapolate this
pattern to a correctly rendered desktop,120Hz picture, or HDMI audio.
