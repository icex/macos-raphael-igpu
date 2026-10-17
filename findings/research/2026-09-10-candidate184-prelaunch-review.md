# Candidate 184 independent prelaunch review

Date: 2026-09-10

## Verdict

**Cleared for the single already planned launch.** This review found no identity,
transport, graphics-policy, artifact, ledger, or one-run-authority blocker. It is
a read-only clearance of the inputs below, not a launch or permission to retry.

## Sealed candidate

- Clean candidate worktree commit:
  `ec02aacea85fe5d652b5da0cee2e8eda344ef278`.
- Manifest: `run/metal-017-184-manifest.json`, SHA-256
  `35b2d1ac983a3b5730c51693460ace4a52d69e58e166641091cf5e275a4f8df3`.
- Run ID: `f32c2266a96dd7e3c91a46b85ac7878d`; build ID:
  `3b398d6d46e14fc89c40d62c4868f407`.
- Card SHA-256:
  `d3e706c7a0f965443923823d9d5653ffdea2ba650e196b5abf975b8636273d46`.
- Staging SHA-256:
  `591f23047e3995316b16cc5e9aa96e09588fcd1eab098d90120195c469b43a24`.
- Build-identities SHA-256:
  `689392c5545aac535e012d4a54e09efe5936ac6df19290099bf2042eee77e021`.
- Archive, build log, build manifest, executable, Info.plist, and SHA256SUMS
  bytes all match their build-identities fields. Both bundle versions are
  `1.0.184`; `physical_tested=false` remains accurate.

The manifest, staging record, and card agree on schema 3 recovery, 180 seconds,
the unchanged 45-second probe policy, `rgpuvmdiag=1`, `rgpuvmroot=4`,
`rgpusubmit=1`, and the dedicated COM2 contract (ISA serial index 1, I/O base
760, 115200 baud, `run/critical.sock`, `critical.txt`). VMID1 observations are
conditional and do not gate probe readiness.

The run nonce decodes little-endian to
`rgpurnlo=0xe3d76da966222cf3` and
`rgpurnhi=0x8d87c75ab8461ac9`, exactly matching the boot arguments. Each required
candidate boot argument occurs once.

The manifest selects `GENERIC_GRAPHICS=off`. All seven live harness hashes in
the manifest match deployed bytes, including the four newly deployed runtime
files. Their candidate-worktree hashes also match. The reviewed runtime contract
produces `-vga none -display none`, rejects generic-device aliases, and omits
`/dev/dri` in this mode.

## Same-boot authority

The live boot remains `73ad3355-80a7-48f1-a8dd-e6f770b41de8`. The schema-2
ledger SHA-256 remains
`2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`,
with one prior launch of a ceiling of three. No active/created/restarting/paused
Docker VM, launch-pending owner, or candidate output directory was present. The
sleep/idle block inhibitor remains active as PID 3777.

The prior live canonical receipt and archived source copy both have SHA-256
`d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`
and bind prior run `4661e574bbd5695d00176d85bfa87325` to recovered ID
`8447b84dca024433a6754a53464e9c14`.

The new policy SHA-256 is
`0152bb1319021d37125b33c7f379988d8938a24ba9fd3953246758cd9ce2b7bd`;
the activation SHA-256 is
`65311f882058257cf52e5695c6a6fbf57293cdab22e4114485d5bcd7f16e79fc`.
They bind the exact manifest, card, candidate, run ID, absent output
`run/metal-017-184`, ledger preimage, prior receipts, recovery helpers, and
worktree tools. The policy keeps `from_max_launches=3`, `to_max_launches=3`,
`additional_launches=0`, `vm_max_seconds=180`, `probe_max_seconds=45`, and
`automatic_retry=false`; the activation is `stage=ONLY` and also forbids retry.

Calling the candidate worktree's `one-run-qualification.authorize` through the
same `experiment.py` hook wiring used by the launch path returned an authorization
object with `errors=[]`. This call only read and validated the authority; it did
not build a reservation or modify the ledger.

No VM, QEMU process, device access, ioctl, sudo, build, staging, reservation, or
launch occurred during this review.
