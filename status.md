# Live status — 2026-10-10

## Candidate 415: virtio network verified, root relay refused, stopped

BootH UUID `189cb4d1-ca4e-48bc-86a2-557ff9ba798d`, source `797a550`,
reached the VMSVGA desktop with eight CPUs and RealTSCOffset. AppleVirtIONetwork
is active; en3 has 10.0.2.15/24. The existing system agent LaunchDaemon is running,
but the bounded relay returned HTTP403: hardened VBox denies /proc/PID/exe access.
No fixed root command or nonce response succeeded. Exact process evidence is
retained for a narrow ownership-check fix; no gate was bypassed during this run.

Root verified awake assertions before network checks. The owned job was removed;
pgrep showed no caffeinate, but cleared assertion bits were not observed. Natural
shutdown reached S5 at 286.889 s, OFF at 286.895 s and termination at 286.939 s,
before the 300 s cap. Original poweroff/unregister succeeded once without errors.
Independent later UUID absence and closed listener passed. No GPU/VFIO exposure.

Evidence: [native relay report](findings/research/virtualbox-root-relay-native-20261010.md)
and companion manifest. Host suite: 1491 passed, eight skipped. Next iteration
must preserve exact VM/process binding while accommodating hardened proc access.
Framebuffer suppression, exclusive transport ownership and VBox Metal remain
unqualified. Host work-awake inhibitor remains active; no native VM remains from415.

## Delivery and paused work

Published dev is `0ecc1715950ea6db3c256fb4930191830bd9ef1b`. Hosted test and
macOS build passed in [run 37998445036](https://github.com/icex/macos-raphael-igpu/actions/runs/37998445036);
the untagged release job was skipped. The exact tested candidate 402 kext/manifest
remain checked in. Main is unchanged.

Candidate 419 integrates completed 415, 416 and 418. Both isolated baseline and
patched full-source VirtualBox userland builds passed, with optional components
excluded; no built VBox binary was installed or executed. The initial patched
build failure and corrected bundled UAPI definitions are retained. The independent
419 audit reverified 57 artifact entries and reproduced both compiled VFIO source
files by zero-fuzz patch application. Tests substitute PGM/map calls and do not
qualify DMA lifetime, reset safety or physical passthrough.

Development is paused at the user’s request. Candidate 420 is source investigation
only. Root owns the separate 417 shutdown/report and final integration checks;
this status does not infer its outcome or authorize a new run.
