# Isolated VirtualBox 7.2.18 baseline build

Candidate 416 starts from dev `0ecc171`. This experiment builds official source in a user-owned scratch directory. It does not install VirtualBox, replace host modules, launch a VM, or expose a physical device.

## Provenance

Source: <https://download.virtualbox.org/virtualbox/7.2.18/VirtualBox-7.2.18.tar.bz2>. The 256,080,202-byte archive SHA256 is `06db4060caadc70346335c0a731ca6667cdabf206de289c64f3f96f2d341b9d0`, matching Oracle's HTTPS `SHA256SUMS`. The attempted `SHA256SUMS.asc` URL returned 404; this is checksum verification, not detached signature verification.

The release `DevPciVfio.cpp` differs from pinned official Git commit `14841851fa211c7faf615978ba385d59947236c6` only in expanded `$Id$` metadata. No DMA patch is applied to this baseline.

Local dependencies are Arch nasm 3.02-1, acpica 20251212-1, and libidl2 0.8.14-7. Their detached package signatures were verified using an isolated GnuPG home importing the installed Arch public keyring. Packages were extracted under `run/c416-build/deps/root`; no package manager installation or system keyring change occurred.

## Recipe and scope

Scratch: `/home/bogdan/macos-vm/run/c416-build/VirtualBox-7.2.18`. Add the dependency prefix's `usr/bin` to PATH and `usr/lib` to LD_LIBRARY_PATH; PKG_CONFIG_PATH points to its `usr/lib/pkgconfig`.

```sh
./configure --disable-kmods --disable-docs --disable-java --disable-python \
  --disable-sdl --disable-opengl --disable-extpack --disable-qt \
  --disable-hardening --with-makeself=/usr/bin/echo
```

The makeself placeholder allows configure without creating an installer; packaging is not qualified. `LocalConfig.kmk` disables additions and validation-kit packaging and enables testcases. Source `env.sh`, then run bundled `kmk -j8`. Main/XPCOM, VBoxManage, headless, and VFIO remain enabled. Disabling hardening is confined to these research binaries; no installed hardened binary is changed.

The installed module reports 7.2.18 revision 175117 and support ABI `0x00390002`, matching the source interface constant. This is not proof that newly built userland can safely run against that module; no runtime is authorized by this build result.

## Result

The complete `kmk -j8` build exited 0. Eight principal outputs are hashed in `run/c416-build/build-result.json`: VBoxManage, VBoxHeadless, VBoxSVC, VBoxXPCOM.so, components/VBoxC.so, VBoxDD.so, VBoxVMM.so, and VMMR0.r0. There are 242 executable files in the testcase output directory; they were built, not executed. The actual VBoxDD `Bus/DevPciVfio.o` exists and its compilation appears in the retained build log.

`ldd` reports no unresolved dependencies for VBoxManage, VBoxHeadless, VBoxSVC, VBoxDD.so, VBoxVMM.so, and components/VBoxC.so. The build retained nonfatal GCC diagnostics, DocBook external-entity warnings, and linker warnings about the type/size of `SUPTracerFireProbe`; exit 0 does not erase these. No C/C++ source correction was needed. The first configure attempt failed on missing makeself; the second used the explicit packaging placeholder above and passed.

This qualifies a full baseline source compilation with the selected disabled optional components. It does not qualify Qt, OpenGL, Guest Additions, host kernel-module compilation, installed-driver runtime compatibility, a guest boot, or physical VFIO DMA. The next bounded step is to apply the reviewed transactional DMA changes to a separate build and compile the full affected production callbacks before considering a PGM RAM-lifetime API. Physical exposure remains blocked by the unresolved authoritative backing-lifetime/reset contract.

Evidence: [hashed build inputs and outputs](virtualbox-isolated-baseline-build-evidence-20261010.json). Scratch logs and binaries remain outside Git.
