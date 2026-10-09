# Console source package and next installation qualification

Candidate363 packages the exact installer, three Objective-C sources, installation
notes and source manifest in a deterministic source ZIP. Explicit-O2 matches the
measured native presenter build class; it does not promise identical binaries
across SDKs. Packaged inputs are checked before file mutation. Installation records
actual compiler/SDK, input/binary hashes and codesign designated requirement/CDHash
outside the signed bundle, after strict signature verification. No signing policy
or app identifier changes; ad-hoc code changes can still require ordinary TCC
renewal. Linux tests cannot qualify macOS compilation, signing or consent.

## Transaction proposal — not implemented yet

1. Preflight architecture, CLT/SDK, manifest and destination ownership. Refuse an
   active console LaunchAgent/presenter/virtual-display session rather than stop it.
   Preflight is not an atomic exclusion; an installer lock and final recheck are
   needed, and an external launch racing publication must remain a documented limit.
2. Create a private staging directory beside the destination app on the same
   filesystem. Compile all three executables, write Info.plist, sign and verify,
   and create provenance before changing any installed path.
3. Stage launcher and LaunchAgent files separately. Journal original hashes and
   whether each path existed; retain prior app/files under an owned transaction
   ID. Commit with renames; because app, support and LaunchAgents are multiple
   paths this is rollback-capable, not one globally atomic filesystem operation.
4. On publication error restore only paths still matching this transaction's
   installed identities; refuse to overwrite concurrent user changes. Retain the
   journal on interrupted/failed rollback. Do not bootstrap or change TCC.
5. Root-owner clean-guest qualification: new user or disposable guest clone,
   package-only inputs, normal permission UI, first desktop/input/default audio,
   next guest login/boot, unchanged app consent, update/rollback and uninstall.
   Keep the VM harness, bounded6000-second sessions and GPU recovery intact.

## VirtualBox remains an objective, with a different missing prerequisite

Oracle7.2's current VBoxManage reference explicitly says PCI passthrough is
unavailable, despite documenting option syntax. The6.1 changelog records removal
of incomplete Linux PCI support that did not handle PCIe. Current accelerated
Guest Additions support lists Windows/Linux/Solaris, not macOS Metal. Therefore
reusing this Raphael PCI driver in an ordinary VirtualBox virtual display cannot
supply acceleration. Restoring suitable isolated PCIe transport or implementing
a new macOS accelerated virtual GPU stack is a separate research gate. A second
QEMU manager frontend is useful progress, not completion of the any-manager goal.

Primary references checked2026-10-09:
- https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html (PCI Passthrough Settings)
- https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/guestadditions.html (Hardware-Accelerated Graphics)
- https://docs.oracle.com/en/virtualization/virtualbox/6.1/relnotes/ChangeLog.html (6.1 removal)
