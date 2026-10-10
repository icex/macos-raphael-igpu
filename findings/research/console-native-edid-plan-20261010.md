# Candidate432: native EDID refresh discriminator

Hypothesis: a QEMU-provided native120Hz mode changes the native framebuffer's
display clock, allowing the extra CGVirtualDisplay to be omitted. Falsifier:
mode readback120Hz while CVDisplayLink remains30Hz and framebuffer timing is absent.

Candidate430 supplies the baseline: presenter-only native1080p rendered correctly
and passed48 Metal readback cases, but nominalCVDisplayLink was30Hz. The holder
path declared120Hz while its clock was60Hz. Keep the signed presenter unchanged;
use a bounded guest job to remove the holder, explicitly select the native mode,
capture it, measure, then restore the original support agent.

Exact new opt-in: CONSOLE_EDID=1440p120 adds QEMU
`xres=2560,yres=1440,refresh_rate=120000` to the existing reviewed32MiB snapshot
pool device. Candidate432/metal226 otherwise keeps candidate402 GPU behavior,
SPICE120, vdagent, manual USB redirection, supervision and recovery checks.
Manifest, outer/inner shell, libvirt admission, plan and running argv bind the
same exact mode. Unknown modes and incompatible profiles refuse before exposure.

## Software/source evidence

`~/macos-vm/run/c432-edid-oracle` links the actual402 QEMU compiled EDID generator
object. Its256-byte1440p120 result has valid base/extension checksums, first DTD
2560×1440 with617.93MHz clock and119.999456Hz. Raw binary SHA256:
591f4a550b0ccfa54339c1618dae95d4517914f561fa8f76da84f38f13debc17.
This is generated EDID evidence; guest acceptance and delivery are untested.

The same oracle shows no first base DTD for4K60,4K120 or5K120. QEMU's fake blanking
makes4K60 clock695.17MHz, beyond the16-bit10kHz field. For larger modes it omits
the base DTD; Bochs'256-byte EDID cannot carry the generator's DisplayID block.
AppleBochVGAFB24G830 reads only the first base DTD plus nine fixed modes.

Decoded local CoreDisplay MPGetVBLTiming@7ff8040e5913 substitutes33,333,333ns
when framebuffer VBL delta is below1000ns; assembly@7ff8040e59b8 confirms the
constant. AppleBochVGAFB overrides neither timing-info nor VBL-interrupt methods.
Inherited IOFramebuffer getTimingInfoForDisplayMode@20de4 returns unsupported.
This supports a missing-timing hypothesis, without proving the live branch.

Read IOFBCurrentPixelClock/IOFBCurrentPixelCount(Real), native mode metadata and
CVDisplayLink together in432. A120Hz label alone cannot qualify120 frame delivery.
If pacing stays30Hz, investigate a native framebuffer timing/VBL implementation;
EDID alone cannot provide arbitrary dynamic Retina window modes or5K120.
