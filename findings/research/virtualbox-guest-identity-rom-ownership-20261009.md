# Guest compatibility identity, ROM injection and presentation ownership

Read-only source audit during candidate397; no VirtualBox GPU attachment or
compatibility qualification. This distinguishes dependencies of the current
implementation from requirements that necessarily belong in a hypervisor.

## Identity: a property-only change is insufficient

`src/RaphaelGPU.cpp::isRaphaelPciMarker` requires vendor1002, registry device73ff,
ATY,bin_image of at least512 bytes and exact `RGPU-RAPHAEL\x01` target marker.
`hasUniqueRaphaelPciMarker` and `isRaphaelHardware` use this predicate to admit
Raphael-specific routes. Accepting164e here alone would not adapt Apple.

The local24G830 KDK personalities in
`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/Info.plist`
and `AMDRadeonX6000Framebuffer.kext/Contents/Info.plist` include73ff in the Navi23
accelerator/controller/wrangler matches, not164e. Our RaphaelGPU personality is an
IOResources plugin; the separate RaphaelConsole personality matches1234:1111.

More decisively, the decoded file
`/home/bogdan/macos-vm/re/decompiled-24G830/HWLibs-full/functions/000b5230_AmdTtlServices__AmdTtlServices.asm`
shows a direct IOPCIDevice::extendedConfigRead16(offset2) at0xb52bd. Its result is
stored at+0x180, then used for device-table selection beginning0xb5349. Injecting a
registry device-id does not translate this configuration-space read. The existing
`wrapTtlSetDevCap` retries internal revisions0..2, preserving the incoming deviceID;
it does not translate164e to73ff. Candidate395's retained serial log records the
capability lookup with device73ff/intRev0xf/extRev0xcb.

Framebuffer `AmdAsicInfoNavi2::populateDeviceInfo@0x3b252` also obtains its device
field from MMIO strap0xd31; `AmdAsicInfo::refresh@0x3b8c6` falls back to PCI offset2
only when that field is zero. Candidate395 logs GPUCAP device0xff00 while TTL sees
73ff, illustrating why these identities must not be conflated. These functions
are in `/home/bogdan/macos-vm/re/roadmap-24G830/AMDRadeonX6000Framebuffer-full/functions/`.

A potentially cleaner guest adaptation would preserve real PCI identity while
providing scoped matching and internal compatibility-ID translation only for the
marked Raphael device. Constructor/table-selection consumers require audit before
choosing a route. This is a proposal, not implemented or proven sufficient. Current
QEMU configuration-space spoofing is a tested dependency; a VirtualBox host override
has not been proven the only solution.

## ROM: Apple prefers the injected image

In the same framebuffer decoded directory,
`000170b4_AMDRadeonX6000_AmdBiosParserHelper__readAtomBios.c` calls
`readEfiAtomBiosImage` first and falls back to `readPciAtomBiosImage` only on failure.
`00017188_AMDRadeonX6000_AmdBiosParserHelper__readEfiAtomBiosImage.c` reads OSData
`ATY,bin_image`, copies and validates it. Inferred decompiler prototypes are not
ABI declarations; function names/addresses and control flow are the source evidence.

`tools/ocprop.py` already injects this image and target marker. Thus retaining the
exact injected graft is a source-supported way to investigate removal of an external
hypervisor romfile. It is not proof that the raw native ROM works. `tools/mkrom.py`
supplies missing PSP-directory and VRAM-info tables required by Apple's selected
path, plus display-path normalization.

Read-only retained-file hashes:

| File under /home/bogdan/macos-vm | Bytes | SHA256 |
| --- | ---: | --- |
| igpu-vbios.rom |44544|b77d1d7f5d8a402936b60f1e84e89ccfcb0f320c2490ec9f8df11bcbb8742123|
| run/gpu-patched.rom |46592|3c6977ee2769b0b5fe96c2f99581806afe53f93e108fcff2f0c177a276c1e901|
| run/gpu.rom |46592|3c6977ee2769b0b5fe96c2f99581806afe53f93e108fcff2f0c177a276c1e901|

Candidate395's retained manifest binds the latter ROM digest. Original master-data
entries9(PSP) and28(VRAM) are zero; current graft entries are0xb160 and0xae00.
All three retained files have PCIR1002:13c0: this graft is not a73ff PCIR-ID patch.
No live VFIO ROM region was opened; retained original bytes do not prove current
VFIO ROM availability or contents.

The narrow future discriminator on the qualified QEMU transport is removing only
external ROM exposure while retaining the exact injected graft, then separately
investigating real164e with reviewed guest compatibility adaptation. Both require
explicit candidate integration, preserving admission and recovery contracts.

## VBoxVGA is not just a new PCI match

`src/ConsoleBridge.cpp` directly programs VBE geometry, writes its mapped aperture
and disables VBE on stop. It currently matches the presentation-only Bochs device,
including class038000, and uses the custom immutable snapshot protocol. It has no
generic arbitration with an EFI/macOS boot-framebuffer owner. Attaching the same
behavior to VBoxVGA could leave two services writing its aperture or changing modes.
A future adapter must qualify boot-console takeover, exclusive publication ownership,
register/layout semantics, immutable frame delivery and shutdown restoration. Merely
changing PCI IDs or exposing an aperture is not a safe complete presentation port.
