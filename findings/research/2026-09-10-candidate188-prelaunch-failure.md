# Candidate 188 prelaunch failure (2026-09-10)

The one authorized ordinary run did not reach Docker or QEMU. Immutable copies
of the launcher log, user journal, staged ledger, output, and launcher scripts
are under `findings/research/2026-09-10-candidate188-prelaunch-evidence/` with
`SHA256SUMS`. The frozen launcher log copy contains exactly:
`error: no X11 socket at /tmp/.X11-unix/X0`. The corresponding user journal is
unit `rgpu-launch-f356b4cfc9a0451a9afda1e4dfb206f0.service`; it records the
supervised launch command, then `VM launcher exited before container
identification`, followed by normal systemd failure/stop. The run output is
`/home/bogdan/macos-vm/run/metal-021-188-output` with empty serial/critical
captures, `shutdown.json` null, and verdict `INVALID` / `identity_or_route_missing`.

## VFIO boundary

This is not a GPU experiment cycle: no container ID, readiness, guest boot,
or exposure evidence exists. The control flow also establishes that VFIO was
not opened. `vm-supervision.py` starts `macos-vm.sh` and waits for Docker
container identification; `macos-vm.sh` checks for `/tmp/.X11-unix/X0` at line
119 before constructing the VFIO arguments or entering the GPU branch around
line 190. Since the only launcher output is that X11 check and no container was
identified, execution stopped before VFIO device arguments or QEMU invocation.
Host-after independently remains unchanged and safe: boot
`3bca3e47-1f28-4f78-af00-5dbf76b00620`, `vfio-pci`, group 31 accessible, active
power, empty reset methods, no VM, and watchdog/capture/sleep guards true.

## Resume assessment

The existing `--resume-prelaunch` mode is tied to the pinned historical 173/174
EINVAL continuation and its specific proof pair. This candidate 188 run does
not carry that historical proof, so generic container-identity absence cannot
by itself authorize continuation. Sol is independently auditing whether a new
bounded proof path can preserve the invariants. Do not edit the ledger, reuse
the reserved run ID, extend its budget, or treat the empty capture as a GPU
result.
