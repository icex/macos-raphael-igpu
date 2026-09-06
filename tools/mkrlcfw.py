#!/usr/bin/env python3
"""Embed this machine's own RLC firmware into the plugin as a C array.

Why: Apple's stack hands the PSP the full Navi 23 IP firmware set, and the Raphael PSP
rejects the RLC members of it -- the save/restore lists are register lists describing
GC 10.3.4's register file, and this chip is GC 10.3.6. gc_10_3_6_rlc.bin is the same
firmware signed for this silicon.

That Apple's descriptor sizes match this file's payload sizes exactly for 4 of 6 RLC types
(RLC_G 0x6200, CNTL 0x250, GPM 0x600, LX6 iram 0x10200) is what establishes the calling
convention: Apple passes the PAYLOAD at ucode_array_offset_bytes with length
ucode_size_bytes, not the container. The two that differ -- SRM (0x5ec0 vs 0x4480) and LX6
dram (0x4200 vs 0x10200) -- are the ASIC-specific ones, which is exactly the mismatch.

The whole file is embedded verbatim and the plugin parses rlc_firmware_header_v2_2 at
runtime, rather than baking offsets in here: one array, and the offsets cannot drift out of
sync with the bytes.

AMD firmware is NOT committed to this repository -- the header is generated at build time
from /lib/firmware and is gitignored.

    ./mkrlcfw.py [-o build/src-rgpu/rlc_fw.h] [--fw /lib/firmware/amdgpu/gc_10_3_6_rlc.bin.zst]
"""
import argparse, os, struct, subprocess, sys

HDR_V2_2 = 0xac          # sizeof(rlc_firmware_header_v2_2)
FIELDS = {               # byte offset -> (name, is_offset_field)
    0x14: ("ucode_size_bytes", False),         0x18: ("ucode_array_offset_bytes", True),
    0x74: ("save_restore_list_cntl_size", False), 0x78: ("save_restore_list_cntl_offset", True),
    0x84: ("save_restore_list_gpm_size", False),  0x88: ("save_restore_list_gpm_offset", True),
    0x94: ("save_restore_list_srm_size", False),  0x98: ("save_restore_list_srm_offset", True),
    0x9c: ("rlc_iram_size", False),               0xa0: ("rlc_iram_offset", True),
    0xa4: ("rlc_dram_size", False),               0xa8: ("rlc_dram_offset", True),
}

def read_fw(path):
    if path.endswith(".zst"):
        return subprocess.run(["zstd", "-dcq", path], capture_output=True, check=True).stdout
    with open(path, "rb") as f:
        return f.read()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fw", default="/lib/firmware/amdgpu/gc_10_3_6_rlc.bin.zst")
    ap.add_argument("-o", default="build/src-rgpu/rlc_fw.h")
    ap.add_argument("--toc", default="/lib/firmware/amdgpu/psp_13_0_5_toc.bin.zst")
    ap.add_argument("--kdk", default="kdk/x/System/Library/Extensions/AMDRadeonX6000HWServices.kext"
                                    "/Contents/PlugIns/AMDRadeonX6000HWLibs.kext/Contents/MacOS"
                                    "/AMDRadeonX6000HWLibs")
    ap.add_argument("--toc-vma", dest="toc_vma", type=lambda x: int(x, 0), default=0x1155d40,
                    help="VMA of _aPSP_TOC_SIGNED in HWLibs")
    ap.add_argument("--toc-vma2", dest="toc_vma2", type=lambda x: int(x, 0), default=0xeb80f0,
                    help="VMA of _TOC_TABLE in HWLibs")
    a = ap.parse_args()
    if not os.path.exists(a.fw):
        sys.exit(f"mkrlcfw: {a.fw} not found -- is linux-firmware installed?")
    d = read_fw(a.fw)

    u32 = lambda o: struct.unpack_from("<I", d, o)[0]
    if u32(0) != len(d):
        sys.exit(f"mkrlcfw: size_bytes {u32(0):#x} != file size {len(d):#x}")
    hdr = u32(4)
    hvM, hvm = struct.unpack_from("<2H", d, 8)
    if (hvM, hvm) != (2, 2) or hdr != HDR_V2_2:
        sys.exit(f"mkrlcfw: expected rlc_firmware_header_v2_2 (0xac), got v{hvM}.{hvm} hdr={hdr:#x}")

    print(f"mkrlcfw: {os.path.basename(a.fw)}  {len(d)} bytes  header v{hvM}.{hvm}")
    for off in sorted(FIELDS):
        name, is_off = FIELDS[off]
        v = u32(off)
        print(f"  {name:34s} @{off:#04x} = {v:#x}")
        if is_off and v >= len(d):
            sys.exit(f"mkrlcfw: {name} {v:#x} is past end of file")

    # ---- Apple's embedded signed TOC, and this chip's replacement for it -------------
    # LOAD_TOC is the FIRST PSP command Apple issues and it fails with 0x8000030a, which
    # leaves tmr_size = 0, so SETUP_TMR then fails with TEE_ERROR_BAD_PARAMETERS and every
    # later firmware load is building on nothing. Apple's TOC lives at HWLibs VMA 0x1155d40
    # as symbol _aPSP_TOC_SIGNED: a $PS1 container, total 0x600, fw_type 0x0000200e,
    # fw_version 0. This chip's own psp_13_0_5_toc.bin carries the SAME 0x600-byte container
    # with fw_type 0x0101200e and fw_version 3, signed with the identical key -- so it is a
    # same-size drop-in, and Apple's is the unstamped one.
    apple_toc = b""
    apple_toc2 = b""
    raph_toc = b""
    if os.path.exists(a.kdk) and os.path.exists(a.toc):
        k = open(a.kdk, "rb").read()
        # HWLibs __DATA has vmaddr == fileoff, so the VMA is the file offset directly.
        apple_toc = k[a.toc_vma:a.toc_vma + 0x600]
        # There are TWO 0x600-byte $PS1 TOC containers in HWLibs and only one is submitted:
        #   _aPSP_TOC_SIGNED @0x1155d40  fw_type 0x200e
        #   _TOC_TABLE       @0xeb80f0   fw_type 0x0     <- unstamped
        # psp_tmr_init takes its TOC from runtime fields psp+0x3588/+0x3580, so which one it
        # is cannot be read statically. LOAD_TOC fails with 0x8000030a = "unrecognised
        # firmware type", and an FW ID of 0 is exactly that, so emit both find patterns and
        # replace whichever is present.
        apple_toc2 = k[a.toc_vma2:a.toc_vma2 + 0x600]
        t = read_fw(a.toc)
        toff, tsize = struct.unpack_from("<I", t, 0x18)[0], struct.unpack_from("<I", t, 0x14)[0]
        raph_toc = t[toff:toff + tsize]
        print(f"mkrlcfw: TOC2 _TOC_TABLE fw_type="
              f"{struct.unpack_from('<I', apple_toc2, 0x58)[0]:#x} "
              f"ver={struct.unpack_from('<I', apple_toc2, 0x60)[0]}")
        print(f"mkrlcfw: TOC  apple fw_type={struct.unpack_from('<I', apple_toc, 0x58)[0]:#x} "
              f"ver={struct.unpack_from('<I', apple_toc, 0x60)[0]}  ->  "
              f"{os.path.basename(a.toc)} fw_type={struct.unpack_from('<I', raph_toc, 0x58)[0]:#x} "
              f"ver={struct.unpack_from('<I', raph_toc, 0x60)[0]}  ({len(raph_toc)} bytes)")
        if apple_toc[0x10:0x14] != b"$PS1" or raph_toc[0x10:0x14] != b"$PS1":
            sys.exit("mkrlcfw: one of the TOC blobs is not a $PS1 container")
        if len(apple_toc) != len(raph_toc):
            sys.exit(f"mkrlcfw: TOC size mismatch {len(apple_toc)} vs {len(raph_toc)}")
    else:
        print("mkrlcfw: KDK or toc firmware absent -- no TOC substitution emitted")

    def carr(name, blob):
        if not blob:
            return ""
        rows = "\n".join("    " + " ".join(f"0x{b:02x}," for b in blob[i:i + 16])
                          for i in range(0, len(blob), 16))
        return (f"static const uint8_t {name}[{len(blob)}] "
                f"__attribute__((aligned(64), used)) = {{\n{rows}\n}};\n\n")

    body = "\n".join(
        "    " + " ".join(f"0x{b:02x}," for b in d[i:i + 16])
        for i in range(0, len(d), 16))
    with open(a.o, "w") as f:
        f.write(f'''// GENERATED by mkrlcfw.py from {os.path.basename(a.fw)} -- DO NOT EDIT, DO NOT COMMIT.
// This machine's own RLC firmware, signed for GC 10.3.6. The plugin parses
// rlc_firmware_header_v2_2 out of these bytes at runtime, so no offsets are baked in here.
#pragma once
#include <stdint.h>

{carr("kAppleToc", apple_toc)}{carr("kAppleToc2", apple_toc2)}{carr("kRaphaelToc", raph_toc)}#define RGPU_HAVE_TOC_FW {1 if apple_toc else 0}
static const uint32_t kTocSize = {len(apple_toc)}u;

static const uint32_t kRlcFwSize = {len(d)}u;
// __attribute__((used)) is required: with only a few bytes read directly the compiler
// constant-folds those and discards the rest of the array, silently producing a kext
// with no firmware in it.
static const uint8_t kRlcFw[{len(d)}] __attribute__((aligned(64), used)) = {{
{body}
}};
''')
    print(f"mkrlcfw: wrote {a.o} ({os.path.getsize(a.o)} bytes of C for {len(d)} bytes of firmware)")

main()
