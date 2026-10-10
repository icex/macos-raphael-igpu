# Candidate441: raw-primary GPU scaling discriminator

Only full-field4K performance active; normal host viewer, no fullscreen/input grabs/automaticUSB.
440 increased refresh attempts but did not improve delivered IDs. Historical380 scaled Cairo
cost and upstream pending replacement motivate GPU scaling while preserving full4K source.

Research patch applies to exact c424 spice-gtk0.42 client source, retaining prior USB/input fixes.
It changes host renderer only: optional RGPU_RAW_TEXTURE=1, client mouse mode, xRGB32 raw CPU
primary, synchronous BGRA dirty-union uploads, independent desktop GtkGLArea, linear filter,
opaque alpha, primary/crop invalidation and temporary Cairo fallback; default Cairo unchanged.
No serverGL/DMABUF/firmware changes. Keep CPU ROI/get_pixbuf and GL FBO verification distinct.

All13 upstream client tests pass. Synthetic control links the actual GTK library object files
and creates a private CPU primary with varyingX and paddedstride. No VM, VFIO or guest runs.
Host RX9070XT Mesa26.2.2 hardware GL, source641x481: exact1:1 all308321RGBpixels match;
viewport480x300 content400x300 centeredx40, bilinear pixel-center oracle maxerror1,
zero pixels exceeding1 and zero nonblackletterbox. Outputs/logs in run/c441-gl-*-check.json.
Synthetic fixture emits a no-display-channel assertion during construction; no real channel
or input is exercised. These checks do not qualify native desktop/input/crop/context lifecycle.

Readback request is bounded16hex optionallyLF; PACK alignment/rowlength/skips/PBO reset and
restored; complete closed file published via exclusive hardlink, partial removed. Atomic
visibility is not fsync crash durability. Readback disabled during performance measurement.

Pending: native controlled Cairo vsGL benchmark at actual1920logical/3840backing scale2,
source60 and normal1440x900/GDK1 viewer, rawOFF on439 server image (440 pacing reverted).
Verify actual GL rendered desktop separately, measure decoded IDs and issued GL renders
separately; neither proves physical scanoutFPS. Preserve original runner and recovery receipts.
User: finish this iteration; if no meaningful4K gain, clean up, update all docs, push dev with
exact hostedCI green and leave an explicit resume prompt. Other roadmap work stays on hold.

Fixture recipe: copy findings/research/fixtures/raw-gl-fixture.c into patched src/ and add a
private executable with objects=spice_client_gtk_lib.extract_all_objects(recursive:true),
dependencies=[spice_client_glib_dep,spice_gtk_deps,spice_wayland_deps]. Arguments are sourceW,H,
viewportW,H and two reservedzeros. Requestfile under RGPU_RAW_GL_CHECK_DIR and RGPU_RAW_TEXTURE=1.
