#!/usr/bin/env python3
"""Cross-build a prepared, patched Lilu 1.6.8 tree on Linux without signing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tempfile


PRODUCT = "Lilu"
VERSION = "1.6.8"
BUNDLE_ID = "as.vit9696.Lilu"

CPP_SOURCES = tuple(f"Lilu/Sources/{name}" for name in (
    "kern_api.cpp", "kern_compression.cpp", "kern_cpu.cpp", "kern_crypto.cpp",
    "kern_devinfo.cpp", "kern_disasm.cpp", "kern_efi.cpp", "kern_file.cpp",
    "kern_iokit.cpp", "kern_mach.cpp", "kern_memmem.cpp", "kern_nvram.cpp",
    "kern_patcher.cpp", "kern_policy.cpp", "kern_qsort.cpp", "kern_rtc.cpp",
    "kern_start.cpp", "kern_user.cpp", "kern_util.cpp",
))
C_SOURCES = (
    "Lilu/Sources/kern_ubsan.c",
    "capstone/cs.c", "capstone/MCInst.c", "capstone/MCInstrDesc.c",
    "capstone/MCRegisterInfo.c", "capstone/SStream.c", "capstone/utils.c",
    "capstone/arch/X86/X86Module.c", "capstone/arch/X86/X86Mapping.c",
    "capstone/arch/X86/X86IntelInstPrinter.c",
    "capstone/arch/X86/X86DisassemblerDecoder.c",
    "capstone/arch/X86/X86Disassembler.c",
    "capstone/arch/X86/X86ATTInstPrinter.c",
    "hde/hde32.c", "hde/hde64.c", "lzvn/lzvn.c", "sha256/sha256.c",
    "umm_malloc/umm_malloc.c",
)
ASM_SOURCES = ("Lilu/Sources/kern_efi_trampoline_x86_64.s",)
ALL_SOURCES = CPP_SOURCES + C_SOURCES + ASM_SOURCES
COMPILE_DEFINITIONS = (
    "-DPRODUCT_NAME=Lilu", "-DMODULE_VERSION=1.6.8", "-DKERNEL=1",
    "-DCAPSTONE_HAS_X86=1", "-DCAPSTONE_HAS_OSXKERNEL=1",
    "-DCAPSTONE_DIET=1", "-DCAPSTONE_X86_REDUCE=1", "-DCAPSTONE_STATIC=1",
    "-DUMM_BEST_FIT=1", "-DUMM_MALLOC_CFG_HEAP_SIZE=0x10000",
    "-DAPPLE_KEXT_ASSERTIONS=1",
)


def source_include_dirs(source: Path) -> tuple[Path, ...]:
    # Xcode provides a generated header map for unqualified Lilu header names.
    return (source, source / "Lilu", source / "Lilu/Headers",
            source / "Lilu/PrivateHeaders", source / "capstone",
            source / "capstone/include", source / "hde", source / "lzvn",
            source / "sha256", source / "umm_malloc")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f"missing dependency directory: {root}")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _contains(parent: Path, child: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def refuse_unsafe_paths(source: Path, toolchain: Path, output: Path) -> None:
    source, toolchain, output = source.resolve(), toolchain.resolve(), output.resolve()
    if output.exists():
        raise ValueError(f"output already exists: {output}")
    if _contains(source, output) or _contains(output, source):
        raise ValueError("output overlaps prepared source")
    if _contains(toolchain, output) or _contains(output, toolchain):
        raise ValueError("output overlaps toolchain")
    if source == toolchain or _contains(source, toolchain) or _contains(toolchain, source):
        raise ValueError("prepared source overlaps toolchain")


def verify_inputs(source: Path, toolchain: Path) -> dict[str, Path]:
    required_source = ("Lilu/Info.plist", "Lilu.xcodeproj/project.pbxproj") + ALL_SOURCES
    for relative in required_source:
        if not (source / relative).is_file():
            raise ValueError(f"missing prepared-source input: {relative}")
    patched_start = (source / "Lilu/Sources/kern_start.cpp").read_text()
    patched_config = (source / "Lilu/PrivateHeaders/kern_config.hpp").read_text()
    markers = (
        (patched_start, "headlessInit = checkKernelArgument(bootargHeadless)"),
        (patched_start, "getKernelVersion() >= KernelVersion::BigSur && !headlessInit"),
        (patched_config, "bootargHeadless"),
    )
    for text, marker in markers:
        if marker not in text:
            raise ValueError(f"prepared source lacks headless patch marker: {marker}")

    sdk = toolchain / "MacKernelSDK-master"
    linker = toolchain / "cctools-inst/bin/x86_64-apple-darwin-ld"
    libkmod = sdk / "Library/x86_64/libkmod.a"
    clang = Path(shutil.which("clang") or "")
    clangxx = Path(shutil.which("clang++") or "")
    for label, path in (("SDK", sdk), ("Apple linker", linker),
                        ("libkmod", libkmod), ("clang", clang), ("clang++", clangxx)):
        if not path.exists():
            raise ValueError(f"missing build input {label}: {path}")
    return {"sdk": sdk, "linker": linker, "libkmod": libkmod,
            "clang": clang, "clangxx": clangxx}


def _replace(value):
    if isinstance(value, str):
        return (value.replace("$(EXECUTABLE_NAME)", PRODUCT)
                .replace("$(PRODUCT_BUNDLE_IDENTIFIER)", BUNDLE_ID)
                .replace("$(PRODUCT_NAME:rfc1034identifier)", PRODUCT)
                .replace("$(PRODUCT_NAME)", PRODUCT)
                .replace("$(MODULE_VERSION)", VERSION))
    if isinstance(value, dict):
        return {key: _replace(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item) for item in value]
    return value


def materialize_info(template: bytes) -> bytes:
    info = _replace(plistlib.loads(template))
    if (info.get("CFBundleIdentifier"), info.get("CFBundleExecutable"),
            info.get("CFBundleVersion")) != (BUNDLE_ID, PRODUCT, VERSION):
        raise ValueError("failed to preserve Lilu bundle identity")
    return plistlib.dumps(info, fmt=plistlib.FMT_XML, sort_keys=True)


def validate_macho(data: bytes) -> None:
    if len(data) < 32:
        raise ValueError("missing or truncated Mach-O header")
    magic, cpu, _subtype, kind = struct.unpack_from("<4I", data)
    if (magic, cpu, kind) != (0xFEEDFACF, 0x1000007, 11):
        raise ValueError("Lilu executable must be an x86_64 MH_KEXT_BUNDLE")


def _compile(command: list[str]) -> None:
    subprocess.run(command, check=True)


def build(source: Path, toolchain: Path, output: Path) -> Path:
    source, toolchain, output = source.resolve(), toolchain.resolve(), output.resolve()
    refuse_unsafe_paths(source, toolchain, output)
    paths = verify_inputs(source, toolchain)
    output.parent.mkdir(parents=True, exist_ok=True)

    source_before = tree_digest(source)
    sdk_before = tree_digest(paths["sdk"])
    linker_before = sha256(paths["linker"])
    libkmod_before = sha256(paths["libkmod"])
    common = [
        "-target", "x86_64-apple-macos10.15", "-nostdinc",
        "-I", str(paths["sdk"] / "Headers"),
        *(part for directory in source_include_dirs(source)
          for part in ("-I", str(directory))),
        *COMPILE_DEFINITIONS,
        "-mkernel", "-fno-builtin", "-fno-builtin-bzero", "-fno-common",
        "-fno-asynchronous-unwind-tables", "-fno-non-call-exceptions",
        "-mmmx", "-msse", "-msse2", "-msse3", "-mssse3", "-mfpmath=sse",
        "-O3", "-Wall", "-Wextra", "-Wno-unused-parameter",
        "-Wno-deprecated-register", "-Wno-unknown-pragmas",
        "-Wno-unknown-warning-option", "-Wno-vla",
    ]

    with tempfile.TemporaryDirectory(prefix="lilu-build-", dir=output.parent) as temporary:
        stage = Path(temporary)
        obj = stage / "obj"
        bundle = stage / "result/Lilu.kext"
        executable = bundle / "Contents/MacOS/Lilu"
        obj.mkdir()
        executable.parent.mkdir(parents=True)

        kmod = obj / "kmod_info.c"
        kmod.write_text(
            "#include <mach/mach_types.h>\n"
            "extern kern_return_t Lilu_kern_start(kmod_info_t *, void *);\n"
            "extern kern_return_t Lilu_kern_stop(kmod_info_t *, void *);\n"
            "extern kern_return_t _start(kmod_info_t *, void *);\n"
            "extern kern_return_t _stop(kmod_info_t *, void *);\n"
            f'KMOD_EXPLICIT_DECL({BUNDLE_ID}, "{VERSION}", _start, _stop)\n'
            "__private_extern__ kmod_start_func_t *_realmain = Lilu_kern_start;\n"
            "__private_extern__ kmod_stop_func_t *_antimain = Lilu_kern_stop;\n"
            "__private_extern__ int _kext_apple_cc = __APPLE_CC__;\n"
        )
        objects = []
        units = ((kmod, "c"),) + tuple((source / item, "c++") for item in CPP_SOURCES) + \
                tuple((source / item, "c") for item in C_SOURCES) + \
                tuple((source / item, "asm") for item in ASM_SOURCES)
        for index, (unit, language) in enumerate(units):
            target = obj / f"{index:02d}-{unit.stem}.o"
            compiler = paths["clangxx"] if language == "c++" else paths["clang"]
            command = [str(compiler), "-c", str(unit), "-o", str(target)] + common
            if language == "c++":
                command += ["-nostdinc++", "-fapple-kext", "-std=c++14",
                            "-fno-exceptions", "-fno-rtti",
                            "-fno-c++-static-destructors"]
            elif language == "c":
                command += ["-std=c11"]
            _compile(command)
            objects.append(target)

        _compile([str(paths["linker"]), "-arch", "x86_64", "-kext", "-static",
                  "-dead_strip", "-o", str(executable), *(str(item) for item in objects),
                  "-L", str(paths["sdk"] / "Library/x86_64"), "-lkmod"])
        validate_macho(executable.read_bytes())
        info = bundle / "Contents/Info.plist"
        info.write_bytes(materialize_info((source / "Lilu/Info.plist").read_bytes()))

        if (tree_digest(source), tree_digest(paths["sdk"]), sha256(paths["linker"]),
                sha256(paths["libkmod"])) != (source_before, sdk_before, linker_before,
                                                 libkmod_before):
            raise RuntimeError("build input changed during compilation")

        report = {
            "product": PRODUCT,
            "version": VERSION,
            "bundle_id": BUNDLE_ID,
            "architecture": "x86_64",
            "deployment_target": "macOS 10.15",
            "macho_type": "MH_KEXT_BUNDLE",
            "signed": False,
            "prepared_source_sha256": source_before,
            "sdk_tree_sha256": sdk_before,
            "linker_sha256": linker_before,
            "libkmod_sha256": libkmod_before,
            "clang_sha256": sha256(paths["clang"]),
            "clangxx_sha256": sha256(paths["clangxx"]),
            "xcode_project_sha256": sha256(source / "Lilu.xcodeproj/project.pbxproj"),
            "info_plist_sha256": sha256(info),
            "executable_sha256": sha256(executable),
            "source_files": list(ALL_SOURCES),
        }
        (stage / "result/build-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
        shutil.move(str(stage / "result"), output)
    print(output / "Lilu.kext")
    return output / "Lilu.kext"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared-source", required=True, type=Path)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.prepared_source, args.toolchain, args.output)


if __name__ == "__main__":
    main()
