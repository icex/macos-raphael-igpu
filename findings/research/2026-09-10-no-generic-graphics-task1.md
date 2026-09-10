# No-generic-graphics launcher contract — Task 1

Date: 2026-09-10
Baseline: `d421120`

## Implemented boundary

This change implements Task 1 of
`findings/plans/2026-09-10-post-com2-candidate.md` in repository source only.
It does not create the candidate card, stage or deploy a harness, execute QEMU,
open a device, or alter the live VM directory.

`tools/vm-entry.sh` begins from the reviewed live entrypoint whose SHA-256 was
`13912a2b14cc02100c7e1178869fa6c3e1721c1864000d1108de78005333a388`.
For `GENERIC_GRAPHICS=off`, it requires the pinned image launcher shape: exactly
one `-vga vmware` and zero image `-display` tokens. It replaces that VGA with
`none`, requires exactly one `-display none` supplied through authenticated
`EXTRA`, and rejects missing/multiple VGA selectors plus `VGA`, `vmware-svga`,
qxl variants, virtio VGA/GPU variants, `bochs-display`, `ramfb`,
`secondary-vga`, `ati-vga`, `cirrus-vga`, and combined forms such as
`virtio-gpu-gl-pci`. Nonliteral whitespace in the image VGA selector is refused
before substitution. It does not print the complete
QEMU command, which may contain the Apple SMC key.

`tools/macos-vm.sh` validates `GENERIC_GRAPHICS`, supplies `-display none` in
off mode, omits GTK display injection, and omits the host `/dev/dri` mapping.
Historical on mode retains its GTK and host-render behavior.

`tools/vm-supervision.py` forwards `GENERIC_GRAPHICS` through its explicit
systemd environment allowlist while continuing to clear inherited `EXTRA`.
`tools/experiment.py` accepts only the historical launch options or this exact
new object:

```json
{"BOOTDISK_MODE":"custom","NVRAM":"stock","GENERIC_GRAPHICS":"off"}
```

New no-graphics identities include `vm-entry.sh` in `harness_sha256`.
Historical manifests retain their prior two-option contract and harness shape.
The running identity records only graphics-related arguments and their values;
the raw argv and SMC key remain undisclosed. Admission requires exactly
`-vga none -display none` and rejects added or aliased generic devices.

## Offline verification

The entrypoint test executes only a harmless `qemu-system-x86_64` stub. It
checks the resulting argv and refusal behavior for missing/multiple selectors,
unknown mode, display injection, and all named generic-device aliases. No QEMU
binary, entrypoint from the live VM tree, VM, container, or hardware path runs.

The focused entrypoint, supervision, experiment, and redeploy suite passed 136
tests after the final changes. Python compilation and shell syntax checks passed.
A concurrent full discovery ran 613 tests with one explicit skip and one known,
unrelated VMID1 typed-decoder failure while that implementation was being updated;
the coordinator deferred the final full-suite run until that owner declares its
source stable. The five recovery helpers have no diff.

Reviewed-source hashes at this checkpoint:

```
1235ca9ee131b4adde6595da7719b0feb90a80e53cc10e75f285ca3c0be0be80  tools/vm-entry.sh
6819d3b9b4d3857e56da66f3cefe9fd7e3a1a61b4d34951a59495fd3b9f791b5  tools/macos-vm.sh
f5bc60f0ff67de50390722eae5d286f216bbf83ebd2e60ad012641946d024b94  tools/vm-supervision.py
3ce8dbf6d70621a4e148a6c0a039b66d5b5cf7c9fa64e616b00857ca717dfcf7  tools/experiment.py
```
