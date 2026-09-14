# Managed-texture fix delivered from RaphaelGPU

Candidate230 fixes the tested managed texture copy defect without modifying an
Apple binary on disk. RaphaelGPU hooks the native, sleepable getHardwareInfo
boundary, finds the current task's exact cached Metal driver image, and makes a
private copy-on-write change to the constructor immediate. It clears bit27 via
one byte, ff to f7, at image-relative0x13a7e6. Active RX permission is restored
before returning to the native method; original/replacement bytes are verified.

The patch is opt-in (`rgputexdiag=2`) and guarded by driver path, x86_64h header,
UUID906f11a39daf35bdb8eacfd2160fae1a, complete instruction bytes, bounded memory
reads, and a leaf mapping covering the full page. It does not alter proc flags,
force Lilu's obsolete userspace patcher on, or hook global shared-region creation.
No demonstrated kernel-only surface-metadata correction was found; that route
remains unresolved. This is a userspace binary patch delivered by our kext.

Two separate GPU boots of the identical built kext/probe passed96 total copy
cases with122,548,224 pixel comparisons and zero mismatches. Main matrices cover
64x64,1280x1024,1920x1080,2048x2048 across six copy/render/upload paths; each boot
also runs two fresh processes without probe-side patching. Both boots pass1000
additional offscreen render frames, drawable pattern checks and animated
self-window capture checks, with clean guest-requested shutdown and GPU recovery.
The read-only candidate229 preserved the prior two1280x1024 failures, each with
1,310,720 mismatches, providing the immediate baseline.

The headless root-display presentation check still does not match the window;
physical display visibility and general application compatibility are not proven.
No main merge/push. OS updates require revalidation: a changed UUID/instruction
is skipped, so the defect may return. No sealed-system-volume changes were made.

OpenCore's built-in kernel/kext patch facilities cannot directly patch this
userspace shared-cache image. OpenCore can load the tested RaphaelGPU kext, which
now performs the guarded in-memory delivery. The alternative ipsw3.1.718 cache
extraction was tested unmodified, with and without ad-hoc signing: dyld crashed
before driver load. That extractor output is not a viable standalone override.

## Artifacts

- Source: `/home/bogdan/macos-vm/run/worktrees/candidate-230`, branch managed-cow.
- Archive: `/home/bogdan/macos-vm/run/candidate-230-dist/RaphaelGPU-1.0.230-experimental.zip`.
- Exact build identities: `/home/bogdan/macos-vm/run/candidate-230-build-identities.json`.
- Runs: `/home/bogdan/macos-vm/run/candidate-230-results` and
  `/home/bogdan/macos-vm/run/candidate-230-attempt-repeat-results`.
- Matrix audits, GPU-free tests and exact CID/boot/time bindings:
  `/home/bogdan/macos-vm/run/managed-delivery-20260914`.
- Full progression and limitations: current worktree `status.md`.
