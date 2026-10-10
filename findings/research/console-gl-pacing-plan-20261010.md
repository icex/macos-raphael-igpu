# Candidate443: moving GL-output integrity, then GL default vs start-relative pacing

Only full-field4K performance active; all other roadmap work on hold. Host viewer stays a
normal 1440x900 window (GDK1, X11), no fullscreen, input grabs or automatic USB. Host awake.

442 prepared the mapped GL-output token decoder (tools/console-gl-token.py) but its run was
paused by the user during boot: no viewer, source or readback ran, so it produced no GL
evidence. 443 carries that tooling forward unchanged on a fresh worktree from dev.

One card (metal-237), two server arms chosen only by pins, same exact441 raw-primary
GtkGLArea client prefix, rawOFF, source Retina 1920 logical / 3840x2160 backing at 60:

- arm D: `pins-bochs-client-lossless.json` (439 image, default completion-relative pacing)
- arm S: `pins-bochs-start-pacing.json` (440 image, 17ms callback-start pacing)

Arm S's 17ms interval caps refresh at 58.82Hz; it is a pacing discriminator, not a 60Hz
qualification. 440 measured S with the Cairo client (refresh 58/s, client ~22 IDs/s); the
question here is whether S matters once host GPU scaling removed the Cairo scaling cost.

Per cycle, in order:

1. Moving GL integrity (diagnostic, excluded from performance): readback requests into
   RGPU_RAW_GL_CHECK_DIR while the mixed token source runs; decode paired nonce/CRC tokens at
   mapped FBO samples. Verify FBO physical size, full uncropped 3840x2160 primary and rawGL
   child first. Report requested/completed/missing/invalid/duplicate separately. Sparse valid
   samples prove sampled-frame integrity only, not every frame or FPS.
2. Performance (check dir unset): restart viewer without readback, then start the source with
   a duration that outlasts the observer window plus settle, so no observation outlives the
   source. Report full-field and localized phase-interior unique decoded IDs/s.

Run order D then S (then D again if time allows) to expose order/host-activity drift. Keep
source, decoded IDs, GL issued renders, readback quality and lifecycle evidence separate.
