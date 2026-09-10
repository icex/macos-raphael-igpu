# Headless Lilu 1.6.8 offline cross-build

`tools/build-headless-lilu.py` compiles a separately prepared and patched Lilu
1.6.8 source tree into a new output directory. It reads the existing Linux
Clang, MacKernelSDK, Apple `ld64`, and `libkmod.a`; it neither modifies those
inputs nor signs, stages, or deploys the result.

The source list follows the Lilu Xcode target's source phase for x86_64. It
includes Lilu's C++ sources, the x86 Capstone diet/reduced sources, hde32 and
hde64, lzvn, sha256, umm_malloc, and the x86_64 EFI trampoline. The i386 EFI
trampoline is intentionally excluded. Direct Clang include directories replace
Xcode's generated header map. `KERNEL=1` is required because `-mkernel` alone
does not configure the supplied corecrypto headers as kernel headers.

The cross target is macOS 10.15, matching the repository's established plugin
cross-build. A 10.6 probe produced references to `IOService` reserved slots 0
and 1, which the target macOS 15.7.9 KDK kernel does not export. The 10.15 target
uses the actual `configureReport` and `updateReport` slots, matching the pinned
official Lilu x86_64 binary.

## Scratch-build evidence

Prepared source:
`/tmp/lilu-headless-build.oeqNe7/prepared`

Verified output:
`/tmp/lilu-headless-build.oeqNe7/verified-output`

The final build command exited zero. Clang 22 reported warnings in unchanged
Lilu 1.6.8 aggregate initializers and one existing atomic failure-order use;
Apple `ld64` reported its known absent `/System/Library/Frameworks` search
directory. No framework dependency or code-signature load command was emitted.

| Check | Result |
|---|---|
| Executable format | x86_64 `MH_KEXT_BUNDLE` |
| Bundle identity | `as.vit9696.Lilu`, executable `Lilu`, version `1.6.8` |
| Plugin ABI | `_lilu`, `_Lilu_kern_start`, `_Lilu_kern_stop`, `_kmod_info` exported |
| Patched argument | `-liluheadless` embedded |
| Signature | no `LC_CODE_SIGNATURE`; manifest `signed: false` |
| Executable SHA-256 | `53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887` |
| Info.plist SHA-256 | `6714fee51444238c0540814729767485572441435bcf36a158571cf78317a669` |
| Manifest SHA-256 | `e5d2554d29658699dd9535a9b8dd38ca9aae5aa5a12f65508b083d3c519cf378` |
| Prepared source SHA-256 | `3bab4ca1df116bf9824cc4555b3171ea1c2e43176abb9d9fdd0a947aa818052e` |
| SDK tree SHA-256 | `39036632f485a027f8b75fe5a8cfb18fab79d5c7531adae9dc165096e7e14666` |
| Patch SHA-256 | `9c6395c2d135e8813ddc41bc54bcac19a716839debf82c3f0a3da9aa484952de` |

Compared with the pinned official Lilu x86_64 executable, the cross-build has
nine additional undefined symbols. All nine resolve in the extracted Sequoia
15.7.9 / 24G830 KDK kernel used by project preflight: three DriverKit dispatch methods, two
`IOService::init` forms, sized delete, `__bzero`, `__memcpy_chk`, and
`__strlcpy_chk`. The invalid reserved-slot 0/1 references are absent. The build
manifest records the source, SDK, compiler, linker, libkmod, plist, executable,
and Xcode-project hashes; fresh source and SDK digests matched after compilation.

The exact checked kernel identifies itself as Darwin 24.6.0 build
`xnu-11417.140.69.711.44~1` and has SHA-256
`04a501246caf768356f4090a8fd662daf5bbc949993353526c66771f5ba1d8e4`.
Its source KDK DMG has SHA-256
`9e2bb18ed726b805ffc009db30bc4bfe7539ed138746165600b0fd5a77562ed4`.

The candidate-185 Raphael plugin imports 12 public symbols defined by the
pinned official Lilu x86_64 executable: five `KernelPatcher` methods, five
`LiluAPI` methods, `_lilu`, and `_lilu_os_log`. The new Lilu executable defines
all 12 with the same Mach-O symbol types; none is missing. This comparison uses
the Raphael executable with SHA-256
`1aec6dc79bb506ab303acde484da69f93d27bb900feb9fd8a80862aaafd3dd1e`.

```text
KernelPatcher::clearError
KernelPatcher::routeFunction
KernelPatcher::applyLookupPatch
KernelPatcher::getError
KernelPatcher::loadKinfo
LiluAPI::onKextLoad
LiluAPI::shouldLoad
LiluAPI::onPatcherLoad
LiluAPI::releaseAccess
LiluAPI::requestAccess
_lilu
_lilu_os_log
```

This is offline build evidence only. It does not establish that macOS loads the
kext or that the headless initialization path runs.
