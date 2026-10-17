# QEMU/virt-manager desktop integration — candidate 421

The user deferred VirtualBox on 2026-10-10 and requested a good native QEMU /
virt-manager experience, specifically copy/paste and USB passthrough through a GUI.
Preserve the working candidate402 snapshot console and supervised GPU lifecycle.
No additional VirtualBox implementation or VM iteration is part of this work.

## Requested behavior and acceptance

- Bidirectional plain UTF-8 clipboard text through the existing standard SPICE
  agent channel. Explicit persisted enable/disable, legacy default off, no logging
  of clipboard contents, no change to the sealed ScreenCaptureKit application.
  Verify both directions with distinct synthetic ASCII, multiline and Unicode
  strings, repeated ownership changes and disconnect/reconnect. Unsupported
  formats, oversized data, malformed/fragmented messages and stale responses must
  not corrupt the clipboard or break resize. No image/file clipboard claim.
- USB selection from virt-manager's existing SPICE USB dialog. Exactly bounded
  opt-in USB redirection channels, automatic device capture off. Do not mount host
  USB device nodes into the VM container or detach host keyboards/storage/audio
  merely to prove configuration. User selection identifies a noncritical physical
  device for live attach, guest enumeration/use, detach and host restoration.
  If none is available, report GUI/channel validation separately from device use.
- Keep display awake; exercise native console resize, keyboard/mouse, audio and
  normal shutdown/recovery after the integration. Preserve capture shortcomings
  in reports instead of treating a clean recovery as perfect capture.

## Implementation ownership

Root421 owns integration, build/card identity, native runs and UI. Offline422 owns
USB channel/configuration verification; offline423 owns clipboard agent/helper,
preferences and support packaging. Both start from fetched dev4fdd0f3.

## Sources

- https://www.spice-space.org/features.html — clipboard/resolution require guest agent.
- https://www.spice-space.org/usbredir.html — SPICE device selection and redirected channels.
- https://libvirt.org/formatdomain.html — spicevmc USB redirdev and clipboard controls.

Configuration tests and protocol tests are prerequisites, not proof of native
clipboard delivery or physical USB use. New milestones go to dev only after
review, appropriate tests, current docs and hosted CI. Main remains unchanged.
