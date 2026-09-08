#!/usr/bin/env python3
"""Check the current driver's route-table binary ownership without a KDK.

This checks installDiagnostics and the three processKext branches. It complements,
not replaces, symbol/prologue preflight; it is not a general C++ data-flow analyzer.
"""
import argparse
from pathlib import Path
import re


def body_at(code, start):
    opening = code.index('{', start)
    depth = 1
    for end in range(opening + 1, len(code)):
        depth += (code[end] == '{') - (code[end] == '}')
        if depth == 0:
            return code[opening + 1:end]
    raise ValueError('unterminated route scope')


def check(source):
    owners = {}
    for name, note in re.findall(r'^static constexpr size_t (kOff\w+)\s*=\s*0x[0-9a-fA-F]+;\s*//([^\n]*)', source, re.M):
        owners[name] = 'FB' if '[fb]' in note else 'X6000' if '[x6]' in note else 'HWLibs'
    # Remove comments and literals so braces/offset names inside logs do not count.
    code = re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"', ' ', source)
    diagnostics = re.search(r'static void installDiagnostics\([^)]*\)\s*\{', code)
    callback = re.search(r'static void processKext\([^)]*\)\s*\{', code)
    if not diagnostics or not callback:
        return ['route checker cannot locate the expected driver functions']
    scopes = [('HWLibs', body_at(code, diagnostics.start()))]
    process = body_at(code, callback.start())
    for domain in ('HWLibs', 'FB', 'X6000'):
        branch = re.search(r'if\s*\(kexts\[Kext' + domain + r'\]\.loadIndex == index\)\s*\{', process)
        if not branch:
            return [f'route checker cannot locate {domain} branch']
        scopes.append((domain, body_at(process, branch.start())))
    errors = []
    for domain, body in scopes:
        for name in sorted(set(re.findall(r'\bkOff\w+\b', body))):
            owner = owners.get(name)
            if owner != domain:
                errors.append(f'{name}: {owner or "unknown"} offset used in {domain} route scope')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    errors = check(args.source.read_text())
    print('\n'.join(errors) if errors else 'route binary ownership: passed')
    raise SystemExit(bool(errors))
