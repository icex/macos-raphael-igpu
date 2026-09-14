# Managed-texture fix delivery: independent read-only recheck

2026-09-14. No VM launch, reset, guest write, patch deployment, or GPU ledger
entry. Host boot read directly: `c369c74e-96ff-4c21-ae85-80ccb269f7d2`.
Docker listed only the inhibitor container, full ID
`146553d4ef2b7030a604b41b0d483b4e3a21828841b5404ea3c8497023e29c87`.
The root checkout is dirty at `93c62a5`; its status predates the relevant work.
Later historical results were read from candidate-228/status.md. Those are
recorded results, not an independently repeated hardware qualification.

## Findings

1. OpenCore's documented patch targets are ACPI tables, the booter, and the
   kernel/kexts. Kernel/Patch does not directly patch a userspace Metal bundle
   simply because its logical path is under System/Library/Extensions.
   OpenCore can inject a kext implementing another mechanism, but that still
   requires implementing and validating the runtime mechanism.
2. Upstream Lilu explicitly disables UserPatcher on Big Sur and later.
   The local Lilu-1.6.8 vmProtect implementation also retains a heuristic
   proc-layout scan and a 0x308 fallback from Mojave. Merely enabling it is
   not a sound delivery path.
3. The original red-team report is more qualified than the quoted summary:
   it reports ABI mismatches against 24G830, but calls missing slide capture
   likely, and says the csflags offset must be validated. This recheck did
   not independently disassemble those kernel functions. Do not convert
   these two risks into observed runtime failures or a proof that a purpose-built
   runtime patcher is impossible.
4. The original settings report enumerates two environment readers and finds
   no writer of main-word bits 27/29/36. Its constructor disassembly agrees
   with the local bytes inspected here. There is no demonstrated configuration
   knob for this fix. Absence of callers inferred from raw pointer searches
   alone would not establish absence of encoded/fixup pointers; the prior
   negative settings-file experiment supplies additional evidence.
5. A standalone patched driver overriding its cached image is a remaining
   delivery candidate. Apple's dyld source contains disk-over-cache loading
   and cache rebinding, along with root-detection and AMFI-dependent path
   controls. This establishes a mechanism, NOT its compatibility with this
   exact Sequoia build, WindowServer, sandboxed clients, or an extracted driver.
   It remains binary modification, potentially involving system-volume and
   signature policy changes. It is worth testing before editing cache subfiles.

## Independently checked patch bytes

Source is an archived segment dump, not an installable Mach-O:
`/tmp/claude-1000/-home-bogdan-src-macos-raphael-igpu/015b73f8-2b58-4b71-acd8-e47ac36b2820/scratchpad/re/mtl__TEXT.bin`.

- Length: 5,253,550 bytes.
- SHA-256: `edea49f14138e3d017dd4e910db94ef19fcb708b3f31e178c208706a7b5da88d`.
- Exactly one occurrence of `48 b8 00 00 70 ff 01 00 00 00` at
  **segment-relative** offset `0x13a7e1`.
- Instruction: `movabs $0x1ff700000,%rax`, followed by OR/store of settings.
- Clearing bit 27 changes the immediate to `0x1f7700000`, i.e.
  `48 b8 00 00 70 f7 01 00 00 00`.

Do not use that segment-relative offset as a dylib or shared-cache file offset.
No patch was written. No installable extracted binary or complete shared-cache
set was found by the focused filename search under /home/bogdan/macos-vm.

## Next discriminating check

Obtain an exact-build standalone driver and establish that dyld loads that copy
instead of the cache in a disposable GPU-free guest, with recorded loaded-image
identity and signature-policy requirements. A raw segment dump is insufficient:
extraction must reconstruct bindings, relocations and Objective-C metadata.
If viable, apply only the checked bit change to a copy with whole-file identity
checks, backup and rollback. Then a separately authorized GPU run must show both
large Managed-copy paths pass in the ordinary process, without the self-patch
child, and retain desktop and cleanup regression evidence.

On OS update, stop applying the patch until the new build, binary identity and
instruction match are re-audited. OpenCore kernel-version bounds cannot pin a
userspace driver build; multiple OS updates may share the same Darwin version.

## Sources

- OpenCore Configuration.tex: https://raw.githubusercontent.com/acidanthera/OpenCorePkg/master/Docs/Configuration.tex
- Lilu kern_start.cpp: https://raw.githubusercontent.com/acidanthera/Lilu/master/Lilu/Sources/kern_start.cpp
- Apple dyld Loader.cpp: https://raw.githubusercontent.com/apple-oss-distributions/dyld/main/dyld/Loader.cpp
- Apple dyld DyldProcessConfig.cpp: https://raw.githubusercontent.com/apple-oss-distributions/dyld/main/dyld/DyldProcessConfig.cpp
- OCLP root-patch/update distinction: https://dortania.github.io/OpenCore-Legacy-Patcher/POST-INSTALL.html
- Local original reports: task `a47c2478b27394996.output` (settings,
  2026-09-14T10:56:32.807Z) and `a94dfeeefb6387060.output` (Lilu,
  2026-09-14T10:41:53.134Z), under
  `/tmp/claude-1000/-home-bogdan-src-macos-raphael-igpu/234f6458-4a87-4d5c-8ee1-cdf8368fbeb3/tasks/`.

Upstream source links were inspected on this date; they are not a claim of
exact-build Sequoia loader equivalence.
