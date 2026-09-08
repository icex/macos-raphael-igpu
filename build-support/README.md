# Release build inputs

`rlc_fw.h.gz` is a compressed copy of the generated header used to build the recorded
1.0.159 experiment. It contains AMD GC 10.3.6 RLC/MEC firmware, PSP 13.0.5 TOC payload,
and two TOC match patterns from macOS 15.7.9 build 24G830 HWLibs. It is retained in this
private repository so CI cannot silently build with firmware substitution disabled.
`inputs.json` pins its decompressed SHA-256, the kernel SDK commit and Lilu version.
AMD's firmware licence is included. The TOC match patterns originate from Apple's KDK;
this is a private research build, not a redistribution of the complete KDK.

Regenerate with `tools/mkrlcfw.py` against the matching KDK and firmware, compress with
gzip mtime=0, update the digest, and run preflight before accepting changed inputs.
Never replace these inputs merely to make a failing digest check pass.
