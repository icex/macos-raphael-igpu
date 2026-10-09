# Candidate393: refresh client mouse coordinates before button transitions

Software preparation only. Native qualification is owned by the run coordinator;
this document does not classify the proposed fix as a native pass.

## Reproducer and source finding

Candidate392's stationary-pointer resize from1440×900 to1000×760 delivers the
actual GTK button at(502.828125,430.796875), but the guest fixture records
window-local(148.57177734375,196.907958984375) instead of
(302.828125,129.203125). Keyboard text is correct, one click is recorded, and
`passed=false` is retained in `run/c392-stationary-final.txt`. These observations
come from the root coordinator; this preparation performs no guest/UI actions.

Stock spice-gtk0.42 `src/spice-widget.c:2222` transforms button coordinates and
checks the canvas bounds, but sends only button transitions. A geometry change
without a subsequent motion event leaves the guest's last absolute coordinates
stale. `motion_event` already uses `transform_input` plus
`spice_inputs_channel_position`. `channel-inputs.c:404–442` and486–514 flush
pending motion/position before sending the button message. This is a concrete
source-supported candidate explanation, pending the same native reproducer.

`tools/spice-gtk-stationary-button.patch` adds one absolute-position call before
real press/release events in CLIENT mouse mode, using the already transformed
coordinates and GDK event's pre-transition button-state argument. Existing bounds,
disabled-input, absent-channel, focus and pointer-grab paths remain intact.
SERVER mode, double-click notifications, key handling and the transport APIs are
unchanged. The channel still owns buffering and final wire button-mask semantics.

## Isolated build and provenance

Source archive: `run/c358-spice-gtk-0.42.tar.xz`, SHA256
`9380117f1811ad1faa1812cb6602479b6290d4a0d8cc442d44427f7f6c0e7a58`.
Original `src/spice-widget.c` SHA256
`99ed37ff1c6ee592f64a53acf415a7f95fa6d287d678af807cfcc0ccb1ecc0f9`.
Patch SHA256
`d37383de7e71f0662ffd54fa16b1f0ed959aa393c37031517074363962799fd6`.

Both source trees, builds and install prefixes live under
`/home/bogdan/macos-vm/run/c393-spice-gtk/`. `spice-gtk-0.42` is patched;
`base-source/spice-gtk-0.42` is the unchanged archive. Their respective directories
are `build`/`prefix` and `base-build`/`base-prefix`. No system files, image or running
viewer are replaced. Exact hashes, dependency versions and logs are retained in
`run/c393-spice-gtk/provenance.json`.

The existing isolated `run/c380-server-study/build-tools/bin` supplies Meson/Ninja
and GLib2.88.3 `glib-mkenums`. The host GLib pkgconfig points at missing generators;
`native.ini` overrides only these build tools. `glib-genmarshal.in` is fetched from
`https://raw.githubusercontent.com/GNOME/glib/2.88.3/gobject/glib-genmarshal.in`,
SHA256 `8691d1119845a6b8e90cfe83a99cd567c8643d62fc5831ea607cf5491a067e81`.
Its Python/version placeholders become `/usr/bin/python3` and2.88.3.

Commands, with `study=/home/bogdan/macos-vm/run/c393-spice-gtk` and
`PATH=/home/bogdan/macos-vm/run/c380-server-study/build-tools/bin:$PATH`:

```sh
# Extract the pinned archive into the two new source directories; patch only one.
patch -d "$study/spice-gtk-0.42" -p1 < tools/spice-gtk-stationary-button.patch
meson setup "$study/build" "$study/spice-gtk-0.42" \
  --native-file="$study/native.ini" --prefix="$study/prefix" --libdir=lib \
  -Dgtk=enabled -Dintrospection=disabled -Dvapi=disabled -Dgtk_doc=disabled \
  -Dusbredir=disabled -Dpolkit=disabled -Dlibcap-ng=disabled \
  -Dwebdav=disabled -Dsmartcard=disabled
ninja -C "$study/build" -j4
meson test -C "$study/build" --no-rebuild --print-errorlogs
meson install -C "$study/build" --no-rebuild
```

Repeat the same configuration with the unpatched source and `base-build`/
`base-prefix` for a matched build control. Project default `debugoptimized`
retains optimized code. GTK3.24.52, GLib2.88.3, spice-protocol0.14.5,
pixman0.46.4 and GStreamer1.28.7 are among the observed build dependencies.

The host lacks wayland-protocols development metadata, so its optional protocol
extensions are absent from **both** isolated builds. GTK's Wayland backend remains
available. USB redirection, webdav, smartcard and policy helper features are
explicitly disabled; these are diagnostic builds, not distribution replacements.
Existing0.42 GI typelibs must be reused; no corrected DisplayPrimary marshaling
or new ABI claim is made. Comparing only distribution stock versus this patched
build would also change build configuration, so retain the unpatched control.

## Validation boundary and native test

The patched library compiles and all11 upstream software tests pass. They do not
exercise the actual stationary-pointer interaction. The source patch is not a
GPU/guest driver change and does not qualify other VM managers or VirtualBox.

The coordinator should compare the unpatched and patched prefixes against the
same guest, same holder/presenter/agent and identical pointer/resize fixture,
retaining real GTK event coordinates, guest click/text output and loaded library
paths/hashes. Ensure the viewer actually loads both intended SPICE libraries:
existing wrapper re-exec code can prepend the old prefix to `LD_LIBRARY_PATH`.
An explicit per-process loader override or isolated launcher must be reviewed;
verify `/proc/PID/maps` before interpreting results. Do not overwrite the existing
manager prefix. Library build success alone is not this verification.
