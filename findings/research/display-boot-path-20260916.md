# Physical-display boot path audit — 2026-09-16

This is source/disassembly analysis with one read-only registry capture in the
postclosure run. No display register/connector patch was made. The user-provided
24G830 source corpus and its companion `re/roadmap-24G830/AMDRadeonX6000Framebuffer-full`
are checked against the exact KDK binary. Native vtable targets and SHA256 are in
[display-boot-vtable-20260916.json](display-boot-vtable-20260916.json).

## What the existing defaults mean

`reportCapabilities_LinkInfo` +0xe074 initializes port=-1, display-type=NONE,
connector-type=0. It reads active path count at path+0xd0 and resolves links.
Those defaults alone do not identify why a usable path/link was absent.

`enableController` +0x14a9a obtains primary/secondary records from controller
getActiveDisplayPath +0x4fa90 and getConnectedDisplayPath +0x4fab4 (stride0x7c8).
`initializeBootDisplay` +0x14ce2 runs only for `isConsoleDevice` +0x14fb0:
framebuffer index must equal parser bootDriverIndex (+0x2688e). With no successful
startup parse, the latter returns0xff, so indices0–3 skip this boot-copy path.

Boot parser is controller+0x7910. `initWithController` +0x265da obtains the PCI
service through getPciDevice +0x4f922 and stores it at parser+0x18.
`readEfiBootData` +0x2665e reads PCI saved-config (required length0x100) and
ATY,EFIBootMode (required length0x203). These are lengths, not format versions.
`parseEfiBootData` +0x267f2 selects the respective populate method; absence of both
returns0xe00002f0. Successful parse sets parser+0x328.
`populatePipeConfigWithBootMode` +0x27018 checks internal versions and increments
path+0xd0 for each valid boot link. `getStartUpMode` +0x268a8 copies the internal
record to the connected path; initializeBootDisplay then copies connected→active.

Two decompiler interpretations were rejected by exact assembly:

- Null getMyLink logs and continues. It does not directly setOffline. Failure of
  getStartUpMode or later setDisplayMode (+0x28dbe) reaches the offline branch.
- initializeFixedDisplayBinding +0x14eec does not fabricate link0xff. It passes an
  output pointer (initial value0xff) to controller getAttribute(type1); that selects
  an existing link with attribute0xd==1. It passes the returned index to getLink,
  and writes that index into both paths. The decompiler lost the output argument.

## Current evidence and limits

Current injected ATY,bin_image and `run/gpu-patched.rom` have SHA256
`3c6977ee2769b0b5fe96c2f99581806afe53f93e108fcff2f0c177a276c1e901`.
MDT display-object entry22 points to0x2284, format1.4, four paths, supported0x0688.
Thus the supplied ROM is not an empty connector table. This does not establish
that Apple's parser successfully consumed every connector.

Current OpenCore injection contains neither boot-config property. The read-only
postclosure GFX0@6 registry capture also lacks them. It also lacks ATY,bin_image:
AmdBiosParserHelper::removeBiosFromRegistry +0x173ac explicitly removes that ROM
property after consumption. Absence of live boot properties is not proof they
were absent at parser entry; only the parser's read path was audited for removal.
Raw evidence: `run/candidate-280-attempt-postclosure-results/gfx0-properties-output.txt`.

The preceding closure serial still contains dccg2_get_dccg_ref_freq,
hubbub2_get_dchub_ref_freq and generic_reg_wait debugger assertions. These retain
the DCN mismatch concern, but do not establish the first failing display operation.
No connectorCount or Stream:null message was found in that capture; logging coverage
is not established, so absence is not positive initialization evidence.

Next discriminating observation: startup parser flags/return, controller link
count and getAttribute(type1) result, correlated with the first DAL/DCN failure.
A synthetic EFI property would bypass an observation without establishing PHY,
HPD/AUX, resource-pool or scanout correctness; there is no justified patch yet.
