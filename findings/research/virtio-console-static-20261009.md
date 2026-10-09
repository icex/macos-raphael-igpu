# Candidate382 preparation: Apple VirtIO console transport

No candidate382 hardware run has occurred. Candidate381's read-only guest plist
inspection found AppleVirtIOConsole matching virtio device type3, and
AppleVirtIOPCITransport matching vendor1af4. It did not expose a standalone
AppleVirtIO executable; this does not establish absence of code in the kernel cache.

The existing local KDK24G830 image was extracted selectively into
`~/macos-vm/run/c382-kdk`. AppleVirtIO230.100.3 is a universal x86_64/arm64e kext,
SHA256 `f0bff51f1fdd3b904b3cf82bd1a5bd61c3d0a17f68f54f25d9c6f4734a1b612b`.
All IOKit personalities equal the guest381 plist inventory. This is a static KDK
reference, not a hash of the guest's loaded kernel-cache code.

Selected x86_64 disassembly supports a bounded multiport attachment experiment:

- `AppleVirtIOPCITransport::probe` at0x12706 recognizes vendor1af4. Device IDs
  1040–107f use device-id minus1040; legacy1000–103f/revision0 reads subsystem
  ID at PCI2e. Both paths are present; this does not qualify their live operation.
- `AppleVirtIOConsole::start` at0x1a530 negotiates features with bit1 and conditionally
  creates queues2/3 with control receive/transmit handlers. This is consistent
  with multiport console feature negotiation; virtual-call offsets are retained
  in the disassembly rather than relabeled as independently resolved functions.
- `attachSerialPort` at0x1ae8a allocates IOSerialStreamSync, sets IOTTYBaseName
  from its name argument, empty IOTTYSuffix, and AppleVirtIOAgentDevice=true.
  This supports checking the exact named BSD endpoint, not assuming it exists.

Artifacts: `c382-kdk/provenance.json`, `AppleVirtIO-x86_64.asm`,
`AppleVirtIO-console-selected.asm`, `AppleVirtIO-PCI-selected.asm`, and
`c381-applevirtio-inspect.txt` under the run directory. The provenance includes
KDK and binary hashes. Capture UART0/1 must remain unchanged. Before any protocol
write, verify exact device/port ancestry and check for an existing claimant;
AppleVirtIOAgentDevice may be relevant to userland matching.

Next discriminator: default-off dedicated standard SPICE agent channel in a fresh
candidate, then guest enumeration without changing presenter, consent or modes.
A successful endpoint/handshake would not establish automatic resizing: the
existing virtual-display service lacks a runtime arbitrary-size control endpoint,
and the 3840×2304 enumerated mode exceeds the snapshot presenter's2160 height.

## Software profile check

The same changed-bbox QEMU software binary accepts the dedicated controller at
PCI slot16, max_ports2, named SPICE port1 and spicevmc backend under TCG, with no
VFIO/KVM/disk/network. `query-chardev` identifies rgpu_vdagent as spicevmc; QMP quit
exits0. Evidence is `run/c382-transport-software-bios/result.json` and its recorded
argv/binary digest. Two preliminary attempts omitted the BIOS search directory
and exited with `could not load PC BIOS`; these were fixture setup failures,
not guest/driver behavior. The successful attempt supplies `/usr/share/qemu`.

The exact-node probe opens no arbitrary tty and exchanges no protocol bytes.
It uses a10s deadline and tests exclusion of a later nonroot child open after
TIOCEXCL, retaining unsupported behavior. Root must first inventory driver
ancestry and existing owners. This is not proof against privileged/future opens
or permission to stop another port owner.
