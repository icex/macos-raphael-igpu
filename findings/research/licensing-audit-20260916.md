# Source provenance and licensing audit — 2026-09-16

Scope: source snapshot `d045c7c388fc9dfc38e02528a5938e3d83e19aaf`; read-only
firmware/source inspection and licence/documentation changes only. No driver,
firmware, generator, packaging code, VM or hardware changes were made. The owner
selected BSD, implemented as BSD-3-Clause for original contributions. This is an
engineering provenance audit, not a legal opinion or a complete infringement scan.

## Finding that changes the earlier risk assessment

Both arrays named `kAppleToc` and `kAppleToc2` are exact contiguous copies of bytes
also distributed in AMD's linux-firmware files. Describing them as necessarily
Apple-exclusive/proprietary Apple content would be unsupported. The existing
extractor obtains them from KDK HWLibs; that historical source does not establish
exclusive ownership. A verified vendor source now exists for identical bytes.

| Existing array | Vendor source | Offset in complete firmware file | Length |
|---|---|---:|---:|
| `kAppleToc` | `amdgpu/sienna_cichlid_sos.bin` | 220112 (`0x35bd0`) | 1536 |
| `kAppleToc2` | `amdgpu/dimgrey_cavefish_sos.bin` | 203744 (`0x31be0`) | 1536 |
| `kRaphaelToc` | `amdgpu/psp_13_0_5_toc.bin` | 256 | 1536 |

Verified by downloading the actual upstream files at linux-firmware commit
[`ab23307cfe7f9366c819025ca3e4778299bc2db2`](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/ab23307cfe7f9366c819025ca3e4778299bc2db2),
then comparing their byte ranges against the decompressed committed header.
All eight arrays in that header have exact upstream matches. The separate VCN
array matches `vcn_3_1_2.bin` at historical commit
[`cdca61c3e725b4eeefdea704b7f462a150f8eef9`](https://gitlab.com/kernel-firmware/linux-firmware/-/tree/cdca61c3e725b4eeefdea704b7f462a150f8eef9).
The current upstream VCN file differs; do not replace the qualified payload with
whatever `main` serves. This audit does not diagnose the upstream revert or its
relevance to this driver.

[Machine-readable evidence](firmware-provenance-20260916.json) records every array
hash, whole-file hash, exact range and commit. A preliminary local scan examined
570 readable AMD firmware files and skipped 129 unreadable entries (including
compressed-file aliases); final positive claims use downloaded upstream files,
not an inference from that incomplete local search. No microcode was disassembled.

The pinned upstream `WHENCE` AMDGPU section lists these files under
`LICENSE.amdgpu`. The actual licence file is at `LICENSES/LICENSE.amdgpu` in that
revision and is byte-identical to the repository's existing notice. It permits
binary redistribution with its notices and prohibits reverse engineering,
decompilation and disassembly. These are redistributable proprietary firmware
bytes, not open-source firmware. Encoding them as a C array does not make their
licence BSD. Whether a particular fragment/packaging practice satisfies all terms
should not be represented as a court-tested conclusion.

## Recommended implementation later: vendor-only inputs, same matching

1. Obtain the complete, unmodified AMD firmware files from pinned linux-firmware
   revisions with their licence; verify full-file SHA-256 before extraction.
2. Generate the two existing find arrays from the proven AMD file ranges instead
   of opening the KDK. Keep the replacement payload, patch counts, driver behaviour
   and whole-pattern matching unchanged. Record each range/hash/source licence.
3. Check that regeneration produces identical arrays and the expected decompressed
   header. The present `mkrlcfw.py` does not generate the later CP additions, so
   simply running it is not yet a complete reproduction of the committed header.
4. Preserve vendor notices and distinguish firmware from BSD source. For a more
   conservative distribution format, ship or fetch intact vendor binary files
   and generate arrays locally, instead of presenting extracted firmware as source.
5. Review the whole release, old assets and source history separately. New notices
   and provenance do not retroactively change the extractor or old packages.

This is preferred because it removes the KDK dependency for these arrays without
weakening the existing match checks or introducing new runtime hooks. It is a
proposed change only; no generator or runtime patch was implemented in this audit.

## Alternative refactors and their limits

- **Runtime locator plus digest:** identify the loaded HWLibs version/UUID, validate
  segment bounds and candidate size, locate a TOC by a verified symbol/offset or
  descriptor, and check its digest before using its live bytes as the search
  pattern. Reject wrong versions, ambiguity or mismatches. This would remove the
  embedded old blobs but needs lifetime/memory-protection and negative-path tests.
  Symbol availability and reliable descriptor access have not been demonstrated.
- **Intercept LOAD_TOC:** replace the descriptor's pointer/length with the vendor
  payload at the relevant native call boundary. This needs independently verified
  ABI, ownership, lifetime and command identification; it is a higher-risk runtime
  change and is unnecessary if identical vendor inputs suffice.
- **Keep extraction local to each user's KDK:** avoids publishing extracted old
  blobs but retains licence/access questions and build dependencies. Merely moving
  copying to build time is not a legal exemption.
- **Search only for `$PS1`:** insufficient identification. Several containers exist;
  a shorter pattern must not replace the whole-match safety contract by itself.

Rewriting an array as numbers, compressing/encrypting it, or reconstructing its
bytes algorithmically is not independent sourcing. A clean-room implementation
cannot be claimed after consulting the original code merely by changing spelling.

## Licence work and remaining boundaries

Added BSD-3-Clause for original project contributions, Lilu BSD notices, APSL and
kmod notices, LGPL-2.1 text/notice for the QEMU AppleSMC patch, and the reviewed
Linux AMDGPU MIT-style notices. Preserved the AMD firmware licence unchanged.
`THIRD_PARTY_NOTICES.md` maps scope, source and licence; the existing release-doc
allowlist now carries the relevant driver notices through a documentation appendix.
QEMU's file-specific LGPL licence supersedes a guess based on the top-level GPL
label; the QEMU patch is not used to relicense the driver.

The SDK deserves a separate follow-up. `tools/build-kext.sh` links `libkmod.a`.
The pinned `Library/kmod/{c_start,c_stop,cplus_start,cplus_stop}.c` headers include
an Apple OS-licence restriction. APSL §2.3 requires source-availability notices in
executable code as well as documentation for executable-only distribution. The
new docs provide the source location and full notices but do not add code-level
notices or determine enforceability of the OS restriction. SDK headers have
per-file terms; including APSL is not blanket clearance for every header. A future
minimal independently authored startup implementation could be investigated,
but removing libkmod alone would not resolve every SDK/header or macOS use issue.

This audit does not establish absence of other copied expressions. The driver
contains native instruction match patterns and research notes contain disassembly
and pseudocode; these need their own necessity/provenance review. AMD and Linux
hardware facts, MIT-licensed implementation, and proprietary Apple implementation
must be distinguished. References to NootedRed/NootRX or Reims are not permission
to import their code; check the applicable revision and licence before reuse.
No rights for such imports are asserted here.

Historical ZIPs and the tracked executable have not been repackaged. No source
history was rewritten and no GitHub releases were removed. Full patched QEMU/Lilu
or VM-image redistribution requires a separate complete inventory. The remaining
macOS contract/interoperability questions depend on jurisdiction and are not
resolved by an open-source licence for this driver.

## Validation

`python3 -B -m unittest discover -s tests`: 953 tests passed, three skipped
(48.321 seconds). Checked local documentation links, complete licence-text
inclusion in the existing release document, byte equality of downloaded licence
copies, and unchanged driver/firmware/generator/packaging/executable files.
No new hardware evidence was collected.
