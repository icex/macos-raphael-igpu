# Libvirt PulseAudio environment regression

Candidate341c failed while libvirt was creating QEMU with `XDG_RUNTIME_DIR not
set`. This is a launcher/audio initialization failure, not a guest Metal result.
The attempted production QEMU create is not assumed to precede VFIO exposure.

The paired software test uses the pinned stock image, libvirt11.9 and QEMU10.1.2,
TCG with128MiB, USB audio on `pa,id=hda`, and Unix SPICE. Its container uses
`--init`, `--network none`, no mapped devices and all capabilities dropped. Only
the existing user PulseAudio runtime/socket directories are mounted for audio.
There is no GPU, KVM, host NIC, macOS disk or guest OS in this test.

Observed in `/home/bogdan/macos-vm/run/c341-audio-env-53238684`:

- Without explicit QEMU environment, paused domain creation fails with the exact
  `XDG_RUNTIME_DIR not set` error. Domain and QEMU process are absent afterwards.
- With `<qemu:env name="XDG_RUNTIME_DIR" value="/xdgrt"/>`, creation succeeds.
  QMP reports `prelaunch`, `running=false`. The actual QEMU process environment
  contains exactly that runtime value, while the controller retains its separate
  `/run/rgpu-study/runtime` private libvirt runtime.
- Normal libvirt destroy removes the domain and QEMU process. The container
  exits naturally with status0; the host's final bounded stop observes it stopped.

This proves PulseAudio backend initialization with the proposed environment
mapping. It does not prove guest USB audio playback, SPICE sound, HDMI sound,
native macOS startup, accelerated output or GPU recovery. Those remain separate
hardware/guest observations.

[Reproduction script](libvirt-audio-env-smoke-20261009.py) and
[artifact hashes/results](libvirt-audio-env-evidence-20261009.json) preserve both
failed and successful configurations.

Source basis: [QEMU10.1.2 paaudio.c](https://raw.githubusercontent.com/qemu/qemu/v10.1.2/audio/paaudio.c)
requires the runtime variable and Pulse pidfile when no explicit server is
configured. [Libvirt11.9 qemu_command.c](https://raw.githubusercontent.com/libvirt/libvirt/v11.9.0/src/qemu/qemu_command.c)
constructs the QEMU environment explicitly and applies `qemu:env` values.
