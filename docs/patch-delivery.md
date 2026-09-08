# Patch delivery

## Current verified path

Enable **both** Lilu.kext and RaphaelGPU.kext in OpenCore `Kernel > Add`, and use
`-lilubetaall` on the tested Sequoia setup. Lilu then patches the AMD kexts as they
load. The original `Invalid Parameter` injection failure was a missing enabled Lilu
dependency. AuxKC delivery loads too late for this controller's initial `start()`.
Use the matching KDK preflight and `esp-kext.sh`; do not disable Lilu injection.

## Historical attempts (superseded)

The record below preserves the earlier experiments, including the incorrect conclusion
that AuxKC was the winning path. Its final deployment recommendation is obsolete.

Four mechanisms were tried, in order. Three fail, and each fails *silently* — which is the real
hazard, because a no-op looks exactly like "the patch didn't help".

## 1. OpenCore `Kernel > Patch` — cannot reach these kexts

Verified empirically: an `AMDRadeonX6000HWLibs` patch and an `AMDRadeonX6000Framebuffer` patch,
both with find-patterns confirmed unique in the target binaries, both `Enabled=True` in the ESP's
config.plist, produced **zero** effect. The BGM stage code stayed at `0xc00c0203` and
`doGPUPanic()` still fired.

The reason is structural. The AMD graphics kexts are prelinked into
`SystemKernelExtensions.kc`, which the OS loads *after* the bootloader has exited. OpenCore only
patches the **boot** kernel collection. This is the same fact that makes the Kernel Debug Kit
necessary to disassemble these kexts at all — on an installed system the bundles are stubs — so
it should have been predictable.

This is also why NootedRed and NootRX are Lilu plugins rather than sets of OpenCore patches.

## 2. Lilu itself — silently disabled on an unknown OS

```
Lilu config: @ automatically disabling on an unsupported operating system
Lilu config: @ found a disabling argument or no arguments, exiting
```

Lilu 1.6.8 predates Sequoia (Darwin 24) and switches itself off, taking every plugin with it.
`-lilubetaall` is required:

```
Lilu config: @ force enabling on an unsupported operating system due to beta flag
Lilu    api: @ force enabling WhateverGreen (167) ... due to beta flag
```

Note the side-effect: until that flag is set, **WhateverGreen and AppleALC are also inert**, even
though they are enabled in config.plist. Easy to reason wrongly about the guest while that is true.

## 3. OpenCore-injecting a hand-built Lilu plugin — rejected

```
OC: Prelinked injection RaphaelGPU.kext (...) - Invalid Parameter
```

Only visible after routing OpenCore's own log to the serial port (`Misc > Debug > Target |= 8`,
`DisplayLevel |= 0x40`); by default it logs to screen only, so this was another silent zero.

Ruled out: the ESP copy is byte-identical to the build output, the Info.plist parses, the Mach-O
magic is valid, and segment layout matches WhateverGreen's shape (`__TEXT` at vmaddr 0,
`__LINKEDIT` filesize reaching EOF, `LC_SYMTAB` + `LC_DYSYMTAB` with relocations). The
`OCAK: ... is not a supported executable` message — which is `DEBUG_INFO`, and INFO was
enabled — never appeared, so the Mach-O parses fine; the failure is later, in
`KextFindKmodAddress` or the post-`MachoExpandImage` re-init.

Not pursued further, because the next mechanism proved the binary was never the problem.

## 4. Installing into the Auxiliary KC — the working direction

`kmutil` **parsed and attempted to link** the same kext, which exonerates the binary:

```
Failed to bind '_lilu' as could not find a kext with 'as.vit9696.Lilu' bundle-id
```

`kextstat` shows Lilu 1.6.8 loaded — but OpenCore injected it into the boot KC, so it exists at
runtime and *not on disk*, and `kmutil`'s Aux-KC linker only resolves against on-disk kext
repositories. So an Aux-KC kext cannot link against a bootloader-injected Lilu. Fix: put
Lilu.kext in `/Library/Extensions` too (and stop OpenCore injecting it, or two Lilus contend for
one bundle id).

Then rebuilding the collection needs one more thing:

```
Missing Developer Kit: As of macOS 13.0, you will need to install a KDK
matching your build 24G830 to rebuild kernel collections.
```

The same KDK already required for static analysis. Install it in the guest at
`/Library/Developer/KDKs/` and `kmutil create -n aux` can link.

## Prerequisites that must all hold

- `csrutil`: **Kext Signing disabled** and Filesystem Protections disabled (`csr-active-config`
  `0x67` gives this). `Authenticated Root` may stay *enabled* — the Aux KC lives on the Data
  volume, so the sealed system volume is not touched.
- Kexts in `/Library/Extensions` must be `root:wheel`. Wrong ownership is a silent load refusal.
- `-lilubetaall` in boot-args.
- A KDK matching the exact build installed **in the guest**.

## Getting the plugin to link — four fixes, in the order the errors revealed them

1. **`Failed to bind '_lilu'`** — Lilu must exist *on disk* in `/Library/Extensions`, not just at
   runtime. `kmutil`'s linker resolves only against on-disk kext repositories, so a
   bootloader-injected Lilu is invisible to it.
2. **`Missing Developer Kit`** — a KDK matching the exact build must be installed **in the
   guest** for `kmutil` to rebuild any collection on macOS 13+. Same KDK already needed on the
   host for disassembly.
3. **`Read-only file system` (Code=30)** — `kmutil install --update-all` insists on rebuilding
   the boot and system collections, which live on the sealed volume while `Authenticated Root` is
   enabled. Build *only* the auxiliary collection instead:
   ```sh
   kmutil create -n aux -a x86_64 -z --kdk /Library/Developer/KDKs/KDK_<ver>_<build>.kdk \
     -B /System/Library/KernelCollections/BootKernelExtensions.kc \
     -S /System/Library/KernelCollections/SystemKernelExtensions.kc \
     -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc \
     -r /Library/Extensions -b as.vit9696.Lilu -b as.rgpu.RaphaelGPU -x
   ```
4. **`Failed to bind '___cxa_atexit'`** — the only actual bug in the plugin. The kernel has no
   `__cxa_atexit`, so static objects must not register destructors. Build with
   **`-fno-c++-static-destructors`**.

Result:

```
as.vit9696.Lilu      1.6.8   /Library/Extensions/Lilu.kext
as.rgpu.RaphaelGPU   1.0.0   /Library/Extensions/RaphaelGPU.kext
```

Then disable OpenCore's `Lilu.kext` injection (and its dependent plugins), or two kexts claim the
same bundle id. `tools/deploy-plugin.sh` does the whole rebuild/push/relink cycle in one command.
