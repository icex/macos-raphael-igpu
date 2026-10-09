# Candidate 409 stock VMSVGA discovery

Offline preparation only. BootF independently reflinks both cleanly shut down
406 bootE disks; original bootE and main images are untouched. Receipt is
`run/c398-vbox-clones/boot-f-preparation.json`; the shared boot-controller lease
was held during reflink creation. Inodes differ; source sizes/mtimes remained
unchanged. No large content reread or VM call was made. Reflinks preserve current
loader and user setup; their VDI UUIDs require the existing isolated VBox home.

Controller adds explicit `--graphics-controller vmsvga`; default remains vboxvga.
Selected value is recorded in scope. Existing 3D-off, no GPU/NIC, exact-identity
cleanup and 300-second ceiling remain unchanged. Source audit predicts a different
PCI/FIFO layout, not a working macOS driver or safe ownership handoff.

Root's bounded command (only after reviewing readiness):

```sh
python3 -B tools/vbox-clone-boot.py --execute \
 --loader /home/bogdan/macos-vm/run/c398-vbox-clones/OpenCore-f-boot.vdi \
 --disk /home/bogdan/macos-vm/run/c398-vbox-clones/mac_hdd_ng-f-boot.vdi \
 --smc-key-file /home/bogdan/macos-vm/run/c398-vbox-clones/smc-key.private \
 --output /home/bogdan/macos-vm/run/c409-vbox-boot-f \
 --seconds 300 --cpus 8 --tsc-mode RealTSCOffset --graphics-controller vmsvga
```

`tools/vbox-display-inventory.py` reads ioreg XML only. Output allows only relevant
VMware/VBox display PCI IDs, reg/assigned-addresses/IODeviceMemory and all framebuffer
services, including those outside PCI ancestry, with an explicit matching-PCI-ancestor
flag; arbitrary properties are excluded. A compressed keyboard command is in
`run/c409-inventory-command.txt`, under 2 KiB, writing `/tmp/c409-display-inventory.json`.
Driver ancestry is not exclusive ownership proof. No register writes, mappings,
FIFO submission, IOSurface import or snapshot ACK is implemented. If the guest
boots, preserve actual PCI/device memory and attached framebuffer evidence before
choosing a writer takeover experiment. Retain screenshots/serial even on failure.

Focused tests: 3 inventory/CLI tests and 13 existing controller tests pass. No
full suite or native guest compilation/execution performed for this preparation.

Final integrated validation after merging dev59422da: 1479 tests passed with
8 skips; log `run/c409-final-full-suite.log`. The standalone name/class substring
filter is explicitly heuristic: an IOFramebuffer subclass with neither name nor
class containing Framebuffer can be missed. Root must also capture the read-only
conformance query `ioreg -r -c IOFramebuffer` to cross-check actual subclass
attachment. An empty heuristic result is not evidence that no framebuffer owns
the display; no ownership-absence conclusion is permitted from this helper.
