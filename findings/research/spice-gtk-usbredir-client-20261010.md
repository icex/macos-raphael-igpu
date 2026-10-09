# Isolated USB-capable SPICE client (candidate 424)

The existing candidate 393 client disables USB redirection and polkit, so it cannot qualify the requested manual device chooser. Candidate 424 builds a separate client with both enabled while preserving the tested stationary-pointer correction. No installed library, existing prefix, device permission, VM, viewer or USB attachment was changed.

## Reproduction and provenance

The 355 source files copied from `run/c393-spice-gtk/spice-gtk-0.42` are byte-identical. This retains spice-gtk 0.42 and `tools/spice-gtk-stationary-button.patch`; source/archive provenance is in [the original report](spice-gtk-stationary-button-20261009.md). New scratch and prefix: `run/c424-spice-gtk`. It uses the same isolated Meson/Ninja and GLib generator overrides as 393, with this configuration:

```sh
meson setup "$study/build" "$study/spice-gtk-0.42" \
  --native-file="$study/native.ini" --prefix="$study/prefix" --libdir=lib \
  -Dgtk=enabled -Dintrospection=disabled -Dvapi=disabled -Dgtk_doc=disabled \
  -Dusbredir=enabled -Dpolkit=enabled -Dlibcap-ng=enabled \
  -Dwebdav=disabled -Dsmartcard=disabled
ninja -C "$study/build" -j4
meson test -C "$study/build" --no-rebuild --print-errorlogs
```

Dependencies available on this host: libusb 1.0.30, usbredir parser/host 0.15.0, polkit 127 and libcap-ng 0.9.6. Compile completed successfully; all 13 upstream tests passed. The ACL tests explicitly substitute `test-mock-acl-helper`; they do not grant host ACLs. Generated configuration defines `USE_USBREDIR`, `USE_POLKIT`, and `USE_LIBCAP_NG`.

**Do not run the upstream install script for this experiment.** It attempts setcap, then chown/chmod-suid fallback. Only `libspice-client-glib-2.0.so.8.8.2` and `libspice-client-gtk-3.0.so.5.1.1` were copied from `build/src` to the new `prefix/lib`, with their SONAME/development symlinks. Shared-library dependencies resolve with the new prefix first. No helper or policy was installed.

## Native launch requirements

Use the [manual-only manager entrypoint](console-usb-redirection-plan-20261010.md) with:

```sh
LD_LIBRARY_PATH=/home/bogdan/macos-vm/run/c424-spice-gtk/prefix/lib:<existing dependencies>
SPICE_USB_ACL_BINARY=/usr/lib/spice-client-glib-usb-acl-helper
```

The explicit helper override is required because the new client embeds its isolated prefix's uninstalled `libexec` path. The existing system helper has `cap_fowner=ep` and the installed polkit policy allows active sessions. Actual permission behavior is untested here. Keep the existing isolated virt-manager Python/typelib/schema paths. Introspection generation remains disabled as in 393: existing typelibs are reused, and the previously documented primary-surface GI layout issue is not fixed or newly qualified by this build.

Root must verify the **actual loaded library paths** from the owned manager process before attributing results; an older wrapper can accidentally prepend the 393 prefix. The next native checks are menu availability, manual-only policy readback, the user-selected Arctis Nova 7X attachment and useful guest I/O, detach/reconnect, device ACL/host-audio restoration, and VM lifecycle. No physical device was opened by this agent. A successful build or mocked ACL test does not establish any of those outcomes.

[Evidence manifest](spice-gtk-usbredir-client-evidence-20261010.json) records 15 artifacts including exact binaries, configuration, logs, source files, helper and policy hashes. `run/c424-spice-gtk/provenance.json` retains the same record outside Git.
