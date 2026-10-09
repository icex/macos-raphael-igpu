# Candidate410: bounded FAT exchange for registry evidence

Offline preparation only. No VM start, host mount, device access, disk-image
extraction from the macOS system disk or guest command was performed here.
Base: fetched dev59422da plus candidate409d6c3f60. The optional exchange medium
changes no GPU behavior and preserves the software-only graphics-controller,
identity, watchdog, deadline and cleanup requirements.

`tools/vbox-exchange.py --prepare` creates a fresh private directory
`run/c410-exchange`, a32MiB raw image with an MBR/FAT16 partition at1MiB, and a
standalone VDI. Label is RGPU410. mtools populates three files without mounting:
the corrected409 registry helper (`inventory.py`), bounded `run410.py`, and
`run.sh`. Raw/VDI qemu-img comparison passes; mtype readback of all three files
matches source bytes. Installed tools: qemu-img11.1.1, mtools4.0.49 and mkfs.fat.
The first draft without the shell wrapper is retained separately in
`run/c410-exchange-before-shell`; it is not the admitted exchange path.

The reviewed helper SHA256 is
`b975a17bc3bf1eb191d221e264b23e54509be394d16f9cbb6378dafb25a68acd`.
The guest wrapper checks that digest, requires `/Volumes/RGPU410`, and refuses an
existing `out/`. It preserves original `/tmp/c409-ioreg.plist`, framebuffer text
and failed helper output as evidence, then takes fresh410 IOService plist,
IOFramebuffer text, OS/build and CPU count. Commands have10-second deadlines;
individual outputs are capped at8MiB. It parses original and fresh plists with
the corrected helper and writes receipt/hashes. Original409 failed JSON is never
used as a successful inventory. Missing originals are recorded explicitly.
The intended short, root-operated guest command is:

```sh
sh /Volumes/RGPU410/run.sh
```

No LaunchAgent, autorun, driver install, capture permission change or boot-disk
mutation is part of this exchange. Native automount, Python availability and
successful evidence collection remain to be tested by root.

## Controller binding and cleanup

`--exchange run/c410-exchange/exchange.vdi` is optional and default absent.
SATA port2 already contains the loader and port4 the macOS disk; exchange uses
only port5/device0. Input must be a private, owned, regular, single-link file in
the exact exchange directory, physically at most40MiB, formatVDI, virtual32MiB,
without a backing file. Hash/size are recorded before launch and rechecked before
attachment. Scoped VBox medium UUID/path/format are verified, then port5's path
and image UUID must match the exact powered-off VM/configuration. Subsequent state
queries retain that attachment binding, including stop/watchdog cleanup.

After verified stopped VM unregister, only that exact medium UUID is closed in
the private registry, without delete. Closure failure remains cleanup_error;
`exchange_closed` stays false. Success records exchange_closed=true and the
post-guest VDI hash. Original VDI and raw preparation artifacts remain intact.
Do not convert/read the output medium while the VM or registry still owns it.
After root verifies the exact scoped result, stopped/unregistered/closed proof and
post-run hash, a new32MiB raw conversion can be read with mtools at offset1048576.
For example, using fresh output paths only:

```sh
qemu-img convert -f vdi -O raw /home/bogdan/macos-vm/run/c410-exchange/exchange.vdi /home/bogdan/macos-vm/run/c410-exchange-return.raw
mcopy -s -i /home/bogdan/macos-vm/run/c410-exchange-return.raw@@1048576 ::/out /home/bogdan/macos-vm/run/c410-exchange-return
```

Inspect copied receipt and SHA256 before treating registry output as evidence;
never execute returned files. Filesystem/API presentation of BARs is still not
proof of exclusive framebuffer ownership or safe mapping.

Focused tests exercise wrong format/backing/size, unsafe containment/link/mode,
UUID/path/format replacement, exact stopped port binding, cleanup UUID/no-delete
and retained exchange identity through state checks. The integrated suite retains
the historical default-without-exchange regressions. Native VBox human-readable
medium identity formatting and volume visibility are not claimed by mocked tests.
