# Third live macOS 15 release — 15.8 / 24H23, 2026-10-13

Candidate486 / metal-280 / run `07e58b88a6d4ac54228c39817904589a`, same compiled
source/executable/build as live 24G830 and 24H32. Host boot
`2e377991-b6d2-4fe5-81dd-fd6afe9999f7`.
Artifacts: `~/macos-vm/run/candidate-486-attempt-24h23r1-results/`.

An independent copy of the tested 15.7.9 clone was updated using Apple's signed
15.8 InstallAssistant.pkg (SHA256
`15e734f617c8b19d90ee1b618f2c1f62b83c87e74a6678ff8564eedd3a0ac0b2`).
Host/guest hashes match. Installation ran GPU-less through a temporary native
launchd job; its nonce, boot identity and source hashes were checked. Apple's
prepare log reports successful 24G830 -> 24H23 preparation. The final live guest
reports 15.8 / 24H23. The installer job and permit were removed/revoked.

- Fresh GPU-less proof resolves all 163 sites and all active userspace contracts.
- CORE_PROBE_PASS; WindowServer/display use the same Navi23 Metal 3 device.
- Main plus two driver-only matrices: 61,274,112 pixels, zero mismatches/unwritten.
- Console-user UID501 window: 196 submitted frames, 193 presentation callbacks,
  zero failed buffers/missing drawables. Both self-captures match the pattern and
  show moving-bar spans [549,628] and [157,236].
- Presentation timestamps are zero in this run. The probe counts timed frames
  only when MTLDrawable.presentedTime > 0; therefore its timed-frame/FPS fields
  are zero and FPS is **unqualified**. Successful callbacks/captures are separate
  functional evidence. Do not claim ~120 fps for this run.
- The whole-host screenshot was taken after QEMU had exited and cannot qualify
  this run's host-window picture. Earlier 24H32 has actual visible QEMU evidence.
- Harness stop-request drives native shutdown: exited-after-guest-request,
  QEMU exit 0, recovery recovered / authorizes_launch=true.

This meets the user's minimum three distinct live 15.x releases before macOS 26
work: 15.7.9, 15.8, 15.8.1, with one unchanged driver and discovery catalog. It does
not claim every past/future release, full desktop conformance or arbitrary private
ABI compatibility. Compatible updates are discovered automatically; unsupported
or ambiguous code/ABI is refused before GPU exposure.

The original 15.8.1 user disk is restored. Tested 15.7.9 and 15.8 clones are retained
under `~/macos-vm/run/macos15-update-tests/`. Next: macOS 26 and update coverage.
