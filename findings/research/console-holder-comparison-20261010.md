# Candidate430: separate the display holder from the presenter

Run `3c4adbc6a0588d091ba5c367ffc9809b`, candidate430 attempt b, uses the
unchanged GPU path and the restartable snapshot-pool QEMU transport.
The user requested automatic screenshot-based comparisons instead of repeated
visual questions. Artifact identities are in
`console-holder-comparison-evidence-20261010.json`.

## Observations

* Extra CGVirtualDisplay at logical1920×1080, backing3840×2160, reports120Hz.
  User confirmed correct colors/picture. Existing AppleBochVGAFB reports85Hz;
  macOS System Information and Displays expose that fallback metadata.
* With both holder and presenter stopped, the user observed a black console.
  This does not isolate whether the holder is required.
* With only the holder removed, the original signed presenter can capture the
  native AppleBochVGAFB display1535231433 explicitly. Native1920×1080 output is
  correct in both QEMU screendump and the real virt-manager decoded pixbuf.
  Screenshots show desktop content and subsequently the changing cadence fixture.
  No separate CGVirtualDisplay process was running during this comparison.
* The exact existing desktop Metal probe returned passed=true, with48 readback
  matrix cases across parent/children, all command/render results OK and zero
  mismatches. The window child submitted124 frames, had no failed command buffers,
  and matched11,616 drawable samples. Its own window captures matched the pattern.
  Parent screen-capture preflight was false and parent pattern_ok=0; this is not
  blanket qualification of that probe's desktop-capture path. Independent QEMU
  and real-client screenshots establish visible output separately.

## Refresh and performance limits

The CGVirtualDisplay120 configuration produced a nominal60Hz CVDisplayLink source.
The100-second client-token test observed4650 unique frames: about60/s during
localized motion and27/s during complete-screen changes. This is a measured
4K copy/transport workload, not a physical HDMI or GPU rendering ceiling.

Without the holder, the native1920×1080/85Hz mode produced a nominal30Hz
CVDisplayLink source,749 draws in25seconds. Client screenshots show output but
do not establish a sustained client delivery rate for this comparison.
Neither an85Hz Settings label nor a120Hz CG mode proves120 presented frames/s.

## Why keep the holder available

The live native mode inventory has15 entries, including5120×2880 and its HiDPI
variant, but no3840×2160 or120Hz mode. Current32MiB snapshot transport cannot
carry a5K BGRA frame. Candidate431's64MiB work is offline and unqualified.

Decoded24G830 AppleVirtualGraphics, under
`~/macos-vm/re/roadmap-24G830/AppleVirtualGraphics-full/functions/`, shows
AppleBochVGAFB::start using nine built-in modes limited by VRAM plus one optional
EDID detailed timing. `readDetailedTimingDescriptor` reads only the first base
DTD, derives refresh rounded to5Hz, and `getInformationForDisplayMode` returns
that or the built-in table. This is a source-supported explanation for limited
modes, not proof that every configuration option has been exhausted.

QEMU's existing xres/yres/refresh_rate EDID properties provide a clean next
native-mode experiment, but its generated timing and the base DTD's size/clock
fields must be checked before claiming4K120 or5K support. Arbitrary Retina window
resize is also unimplemented on this native path. Do not replace the working
holder globally based only on the1080p success.

The comparison uses a bounded launchd job with an EXIT trap restoring the original
support agent. No GPU reset, firmware operation, binary resigning or QEMU restart
is involved. Restoration was verified with both original helpers running again.
The cycle then returned valid CORE_PROBE_PASS. Guest shutdown was requested but
did not complete within its bounded grace; outcome was forced, not clean.
Recovery returned recovered with authorizes_launch=true. No GPU VM remains.
