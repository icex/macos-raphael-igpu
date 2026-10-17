# Live status — 2026-10-10

Candidate398 software-only VirtualBox boot reaches APFS/OpenCore but fails in
VBoxEFI AppleGetVar_Unknown0 (VBoxAppleSim.c145) before macOS kernel boot.
No desktop/Metal qualification. Owned VM powered off and unregistered; no GPU
exposure or main-image writes. Eight focused controller tests pass.
See findings/research/virtualbox-clone-boot-native-20261010.md and artifact manifest.

Most recent physical-GPU run397 completed motion diagnostics, normal guest
shutdown and authorizing recovery. Its full status/evidence is committed on397
atd0f75a2. Host awake blocker remains active; GPU staysvfio-pci,power/control=on.
Dev remainsc1f64d0 with hosted test/build green;398 is candidate-only.
Next: fresh derivative with source-reviewed OpenCore protocol override; separately
399 measures QEMU allocation/copy costs without changing frame ownership.
