# Candidate323: physical HDMI audio experiment

Required by user together with1080HiDPI120. Fresh branch from remote devac52d07.

Audio1002:1640 at7b:00.1 remains separate from graphics7b:00.0. Pass it only
with HDMI_AUDIO=on, as guest00:06.1 beside multifunction00:06.0, spoof1002:ab28
in PCI config. Refuse other devices, groups, addresses, enabled reset methods,
runtime suspension, inaccessible nodes or bus mastering before launch.
Audio PCI bus mastering must also be off after QEMU closes, before the graphics
recovery receipt can authorize reuse. This proves DMA blocked at that boundary,
not complete HDA engine or audible-output qualification.

## Apple pairing

Rechecked exact24G830 AppleGFXHDA binary: unique34-byte instruction sequence
at file0x2af17 in EG::locateAssociatedGraphicsController0x2ae52. This function
iterates sibling IOPCIDevices and compares getBusNumber (vtable0x8e8); all
pcie.0 siblings alias. Default-off rgpuhdmiaudio=1 changes the two calls to
getDeviceNumber0x8f0. Both graphics/audio are required at slot6 on the same
parent bus. Leave remaining BDF publication calls unchanged. No Apple disk
binary, OpenCore layout-id or hda-gfx change. Inspect published GFX BDF0x3000
and HDAU BDF0x3001 in guest before claiming correct matching.

## Host handoff

One-way audio-only binder tools/hdmi-audio-bind.py; no GPU rebinding or PCI
reset. Pin audio awake before any VFIO open, disable reset methods, bind once,
pin awake again. Keep the audio function on VFIO for the remainder of this boot.
All PCM endpoints must report closed and no process may hold a PCM descriptor.
Control-only handles may remain: Linux sound/core/init.c snd_card_disconnect
replaces file operations with shutdown operations and notifies listeners;
snd_card_free waits for release. Intel azx_remove calls snd_card_free, and
azx_free stops streams/chip. Do not kill WirePlumber or user applications.
Binder refuses a live QEMU or open GPU/audio VFIO group. Root-only handoff uses
an announced privileged container, with no normal-path sudo.

## Qualification

Require exact guest pairing, codec/output enumeration, active audio stream and
physical listening confirmation through Samsung audio output. USB/BlackHole
sound remains separate and cannot satisfy this milestone. HiDPI120 remains
open; candidate323 does not force FRL capabilities or overspeed TMDS.
