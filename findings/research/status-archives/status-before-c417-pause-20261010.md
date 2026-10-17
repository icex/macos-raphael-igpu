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

## Delivery and parallel work

Published dev is `0ecc1715950ea6db3c256fb4930191830bd9ef1b`, integrating the
409/410 software console results and experimental 411/413 DMA patches plus 412
Apple-source ownership analysis. Hosted CI run37998445036 is still being watched.
The exact tested candidate402 kext/manifest remain checked in. Main unchanged.
An isolated baseline VBox build is underway in candidate416; installed binaries
and kernel modules are unchanged. That build is not yet qualified or deployed.
