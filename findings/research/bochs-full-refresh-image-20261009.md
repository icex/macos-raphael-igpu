# Candidate352 compatible diagnostic image

Image `sha256:945eea905d337c7a3725ceab5d34175040e938a4eef97730ca14d43b92396196`
(tag `rgpu-qemu-full-refresh:c352`) is built from exact base
`sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
The QEMU binary was compiled inside that base, with the same345 feature flags,
pinned pristine10.1.2 archive and existing readonly Python build dependencies.
Only the explicit nongl refresh and Bochs full-refresh diagnostic patches apply.
Dockerfile copies only the resulting binary into `/usr/sbin/qemu-system-x86_64`.
No default image pin, native launcher, kernel or guest driver changes.

Build container and all four validation containers used network-none, dropped
all capabilities, no-new-privileges and no host devices. All exited0 naturally;
exact container IDs/inspect receipts are retained. The image binary advertises
KVM and TCG plus the diagnostic property defaultfalse. Software tests inside the
image pass default/off/on full pixels, unchanged static recaptures and resize,
with explicit property false/true readback. No physical GPU or KVM guest was
opened by these image checks; TCG/qtest does not qualify native copy cost.

Reproducible directory: `~/macos-vm/run/c352-qemu-full-refresh/`, including fresh
source/build, both patches, build.sh, Dockerfile, inputs, build/image logs,
capability output, inspect files, pixel reports and build-receipt.json. The
adjacent repository evidence pins their hashes, archive, binary and image ID.
Previous research trees/images were not overwritten. Native admission, property
binding, exact running argv and performance/capture/cleanup remain root-owned
future qualification, not results of this software image preparation.
