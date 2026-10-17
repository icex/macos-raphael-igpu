#!/usr/bin/env python3
"""Copy and patch the exact pinned Lilu 1.6.8 source without mutating it."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'build-support/lilu-1.6.8-headless-init.patch'
PINNED_FILES = {
    'Lilu/Sources/kern_start.cpp': 'fe7d404b30a13034bf04c601f387428f9cf66b2f6253f3b50fe35a303497e2f4',
    'Lilu/PrivateHeaders/kern_config.hpp': 'ef006e45191d4dec9219e90f214a87475e08e76da34b82325bd7934449e291d7',
}

def prepare(source: Path, output: Path) -> None:
    source = source.resolve()
    output = output.resolve()
    for relative, expected in PINNED_FILES.items():
        target = source / relative
        if not target.is_file():
            raise ValueError(f'missing {relative}')
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest != expected:
            raise ValueError(f'pinned Lilu source hash mismatch: {relative} {digest}')
    if output.exists():
        raise ValueError(f'output already exists: {output}')
    shutil.copytree(source, output)
    try:
        subprocess.run(['git', 'apply', '--check', str(PATCH)], cwd=output, check=True)
        subprocess.run(['git', 'apply', str(PATCH)], cwd=output, check=True)
    except Exception:
        shutil.rmtree(output)
        raise

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    prepare(args.source, args.output)

if __name__ == '__main__':
    main()
