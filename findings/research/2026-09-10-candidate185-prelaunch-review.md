# Candidate 185 independent prelaunch review

Date: 2026-09-10

## Verdict

**Cleared for the single planned candidate-185 launch.** No source, artifact,
staging, transport, graphics, authority, ledger, or live admission blocker was
found. This is read-only clearance; it did not reserve or launch the run.

## Immutable source and build

- Clean detached worktree commit:
  `c499829dd134402dc9f7227363740720c1a89a15`.
- Build-identities SHA-256:
  `6862ecf47dc09ff30dad5ae391ef63b52a696163c14cdff9804722a08df7f51e`.
- Build ID: `68b28f81b7d5404cb69a7baf2f6117c5`.
- Driver source SHA-256:
  `db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0`,
  unchanged from candidate 184.
- The distribution archive, build log, build manifest, executable, Info.plist,
  and SHA256SUMS all match their build-identities fields. Both bundle versions
  are `1.0.185`, and `physical_tested=false` remains accurate.
- Card `metal-018` SHA-256:
  `1718fc26ffd45550cf9d0187c697af80abeff3ac29ec58ec3899657c6c43985a`.

## Staging and manifest

- Run ID: `2ef50dc9d8b466c5f2521208b5ba87ea`.
- Staging SHA-256:
  `22c9c90dce52a7e8259cf763487fc25ac36c220cf02f9849d9d7b1c35337aa05`.
- Manifest SHA-256:
  `e23b8013bbc8ecdc4374dedc0e89afd6b63287ba1c35450515b59c828e8cafd1`.
- Bootdisk SHA-256:
  `1dc61cf61dc0a98d4370fcb36608421d4077283f1ca46260aaa9f562d1a27843`.
- The run nonce decodes little-endian to
  `rgpurnlo=0xc566b4d8c90df52e` and
  `rgpurnhi=0xea87bab5081252f2`, exactly matching the staged and manifested
  boot arguments. The required `rgpuvmdiag=1`, `rgpuvmroot=4`,
  `rgpucr2uart=2`, `rgpusubmit=1`, and nonce tokens each occur once.

The card, staging record, and manifest agree on schema-3 recovery, the 180-second
VM cap, unchanged 45-second probe gate, optional VMID1 diagnostics, and the
dedicated COM2 contract at ISA serial index 1 / I/O base 760 / 115200 baud.
They also agree on `GENERIC_GRAPHICS=off`. Every deployed harness hash in the
manifest matches the live byte, including `vm-entry.sh`; this seals the reviewed
`-vga none -display none` path and generic-adapter rejection.

## Final reservation correction

The candidate worktree's final locked reservation source now passes the exact
manifest run ID, recovery lease schema, and `launch_options(manifest)` into
`current_identity`. Its regression reaches the real one-run adapter, observes
the no-generic options at both identity reads, and verifies an option mismatch
does not call the ledger replacement. This closes the precise pre-QEMU refusal
seen in candidate 184 without weakening any host, output, receipt, or budget
gate.

## Run-scoped authority and live gates

- Policy SHA-256:
  `4b092ebd67911ccbe79c67807f97e3991ddaa865e9d2ace5ff5fc5b341ff1fca`.
- Activation SHA-256:
  `7076d8328552683824abef35fe8f34e23908086afcdaf0134d7b08d0287bd181`.
- The exact run-scoped policy filename is
  `2ef50dc9d8b466c5f2521208b5ba87ea.policy.json`; the activation is
  `2ef50dc9d8b466c5f2521208b5ba87ea.json` with `stage=ONLY`.
- The policy binds the exact card, manifest, candidate directory, intended absent
  output `run/metal-018-185`, experiment and qualification helpers, recovery
  helpers, receipt copies, and ledger preimage.
- Caps remain `from_max_launches=3`, `to_max_launches=3`,
  `additional_launches=0`, `vm_max_seconds=180`, and
  `probe_max_seconds=45`; automatic extension and retry are false.

The live, archived, and candidate-185 authority-input recovery receipts all have
SHA-256 `d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`
and bind GUI-183 run `4661e574bbd5695d00176d85bfa87325` to recovery
`8447b84dca024433a6754a53464e9c14`. The ledger remains schema 2, one of
three used, at SHA-256
`2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`.

Using the exact candidate-185 `experiment.py` hook wiring,
`one-run-qualification.authorize` selected the run-scoped policy and returned
`errors=[]`. The output remains absent. The live boot ID remains
`73ad3355-80a7-48f1-a8dd-e6f770b41de8`; the sleep inhibitor is active; no
active/created/restarting/paused VM or pending launch owner was observed.

Candidate 184 remains preserved: its legacy policy and activation hashes are
still `0152bb1319021d37125b33c7f379988d8938a24ba9fd3953246758cd9ce2b7bd`
and `65311f882058257cf52e5695c6a6fbf57293cdab22e4114485d5bcd7f16e79fc`.

No source, build, staged media, manifest, authority, ledger, output, VM, device,
or host state was modified during this review. No reservation, QEMU process,
sudo, ioctl, recovery, or transport rerun occurred.
