# Private libvirt emulator discovery PATH correction

Candidate342, based on candidate341 commit084d9e7. This is an offline controller correction; no image, kext, live daemon or running VM was changed.

## Observation

Candidate341d virt-manager rendered the native accelerated desktop, but its details setup logged `Host does not support virtualization type 'hvm' for architecture 'x86_64'`. The retained user journal unit is `rgpu-c341d-virt-manager.service` (2026-10-09 11:59:20). Its global capabilities contained only an i686 guest using `/usr/sbin/qemu-system-i386`. Explicit domain capabilities for `/usr/sbin/qemu-system-x86_64`, x86_64, pc-q35-10.1, kvm succeeded. The error did not mean the running guest lacked KVM.

`tools/vm-entry.sh` prepends `/tmp/rgpu-qemu-shim` so the native launcher hands its expanded arguments to the libvirt controller. The controller previously passed this PATH unchanged into libvirtd. Thus default x86_64 emulator discovery selected the controller shim, while the domain's absolute emulator path remained correct. This is a source-supported diagnosis; an isolated real-daemon capabilities comparison remains the next integration check.

## Source corroboration

Upstream libvirt11.9 `src/qemu/qemu_capabilities.c`:

- `virQEMUCapsFindBinary` (line982) resolves its generated filename with `virFindFileInPath`.
- `virQEMUCapsGetDefaultEmulator` (line991) looks for `qemu-system-<architecture>` using that helper.
- `virQEMUCapsInitGuest` (line1032) returns without adding the guest architecture when capability extraction for that binary fails.

Source: https://raw.githubusercontent.com/libvirt/libvirt/v11.9.0/src/qemu/qemu_capabilities.c
Retrieved source SHA256: `7112c7cb539e6bb46bf281ec9d31262a76cb88ab710850bdf55789f390ec13af`.

## Bounded correction and validation

`start_daemon` now gives libvirtd a copy of the controller environment with the standard system executable PATH, excluding the temporary launcher shim. Private XDG runtime and all other environment values remain intact; the controller's own environment is unchanged. Domain emulator, QEMU audio XDG override, ownership, deadlines, admission and cleanup are unchanged.

The focused regression creates a real shadow executable and confirms an ordinary child process discovers it under the inherited PATH. It then exercises the daemon launch boundary with a harmless Python discovery child and confirms the sanitized environment does not select the shim, while preserving private runtime/run identity. Two additional tests retain failure propagation and bounded launch waiting. No libvirtd, QEMU, VM, device or host input is started by these tests.

Pending: isolated daemon global capabilities must include x86_64 using the real emulator, then a fresh admitted native run must retain manager console/input and cleanup. Do not restart the live341d daemon to apply this change.

Offline full-suite validation: `python3 -B -m unittest discover -s tests` completed successfully; retained log `/home/bogdan/macos-vm/run/c342-offline-tests.log`.
