#!/usr/bin/env python3
"""Read-only compatibility discovery in an Apple fileset kernel collection.

Catalog keys are provenance from the audited baseline, never runtime addresses.
Named functions are verified by instruction-family contracts; anonymous functions
and constant tables require unique section-bounded matches. No build allowlist.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'findings/research/update-portability-20261013/kernel-sites.json'
BUNDLES = {'HWLibs': 'com.apple.kext.AMDRadeonX6000HWLibs',
           'FB': 'com.apple.kext.AMDRadeonX6000Framebuffer',
           'X6000': 'com.apple.kext.AMDRadeonX6000'}


def commands(data, base=0):
    if base < 0 or base + 32 > len(data) or struct.unpack_from('<I', data, base)[0] != 0xfeedfacf:
        raise ValueError('invalid Mach-O header')
    count, total = struct.unpack_from('<II', data, base+16)
    end = base+32+total
    if end > len(data) or count > min(65536, total//8):
        raise ValueError('invalid command extent')
    at = base+32
    for _ in range(count):
        if at+8 > end:
            raise ValueError('truncated command')
        command, size = struct.unpack_from('<II', data, at)
        if size < 8 or size > end-at:
            raise ValueError('invalid command size')
        yield command, at, size
        at += size
    if at != end:
        raise ValueError('command count/size mismatch')


def cstring(data, at, end):
    if at < 0 or at >= end or end > len(data):
        raise ValueError('invalid string extent')
    return data[at:data.index(b'\0', at, end)].decode('utf-8', errors='strict')


def images(data):
    result = {}
    for command, at, size in commands(data):
        if command != 0x80000035:
            continue
        if size < 32:
            raise ValueError('truncated fileset entry')
        _, offset, name_at = struct.unpack_from('<QQI', data, at+8)
        name = cstring(data, at+name_at, at+size)
        if name in result:
            raise ValueError('duplicate fileset entry')
        result[name] = offset
    return result


def image(data, base):
    text = None
    sections = {}
    symbols = {}
    symtab = None
    for command, at, size in commands(data, base):
        if command == 0x19:
            if size < 72:
                raise ValueError('truncated segment')
            name = data[at+8:at+24].split(b'\0')[0]
            vm, _, offset, length = struct.unpack_from('<QQQQ', data, at+24)
            count = struct.unpack_from('<I', data, at+64)[0]
            if count > (size-72)//80 or offset > len(data) or length > len(data)-offset:
                raise ValueError('invalid segment extent')
            if name != b'__TEXT':
                continue
            if text is not None:
                raise ValueError('duplicate TEXT segment')
            text = data[offset:offset+length]
            text_vm = vm
            for n in range(count):
                entry = at+72+80*n
                section = data[entry:entry+16].split(b'\0')[0].decode()
                address, extent = struct.unpack_from('<QQ', data, entry+32)
                if address < vm or address-vm > length or extent > length-(address-vm):
                    raise ValueError('invalid TEXT section extent')
                if section in sections:
                    raise ValueError('duplicate TEXT section')
                sections[section] = (address-vm, extent)
        elif command == 2:
            if size != 24 or symtab is not None:
                raise ValueError('invalid symbol table command')
            symtab = struct.unpack_from('<IIII', data, at+8)
    if text is None or '__text' not in sections:
        raise ValueError('missing executable TEXT')
    if symtab:
        offset, count, strings, size = symtab
        if offset > len(data) or count > (len(data)-offset)//16 or strings > len(data) or size > len(data)-strings:
            raise ValueError('invalid symbol table extent')
        for n in range(count):
            string, kind, _, _, value = struct.unpack_from('<IBBHQ', data, offset+16*n)
            if kind & 0xe0 or kind & 0x0e != 0x0e or not value:
                continue
            name = cstring(data, strings+string, strings+size)
            if name in symbols and symbols[name] != value-text_vm:
                symbols[name] = None
            elif name not in symbols:
                symbols[name] = value-text_vm
    return text, sections, symbols


def matches(text, position, expected, mask):
    return (position >= 0 and position+len(expected) <= len(text) and
            all((a & m) == (b & m) for a, b, m in
                zip(text[position:position+len(expected)], expected, mask)))


def discover_pattern(text, sections, symbols, site):
    expected, mask = bytes.fromhex(site['bytes']), bytes.fromhex(site['mask'])
    if not expected or len(expected) != len(mask) or site['target_delta'] >= len(expected):
        raise ValueError('invalid site contract')
    begin, length = sections[site.get('section', '__text')]
    end = begin+length
    if symbols.get(site['symbol']) is not None:
        symbol = symbols[site['symbol']]
        if site.get('scope_end_symbol'):
            scope_end = symbols.get(site['scope_end_symbol'])
            if scope_end is None or not begin <= symbol < scope_end <= end:
                return None
            # A saved boundary name may not silently span newly inserted functions.
            next_symbol = min((v for v in symbols.values() if v is not None and symbol < v <= end), default=end)
            if scope_end != next_symbol:
                return None
            begin, end = symbol, scope_end
        else:
            position = symbol+site['symbol_delta']
            return (position+site['target_delta'] if begin <= position and position+len(expected) <= end
                    and matches(text, position, expected, mask) else None)
    # Longest exact run is a search accelerator; every masked byte is still checked.
    runs, start = [], None
    for index, value in enumerate(mask+b'\0'):
        if value == 255 and start is None:
            start = index
        if value != 255 and start is not None:
            runs.append((start, index))
            start = None
    if not runs:
        raise ValueError('unconstrained contract')
    first, last = max(runs, key=lambda row: row[1]-row[0])
    anchor = expected[first:last]
    positions = []
    position = begin
    while True:
        hit = text.find(anchor, position, end)
        if hit < 0:
            break
        position = hit+1
        candidate = hit-first
        if candidate >= begin and candidate+len(expected) <= end and matches(text, candidate, expected, mask):
            positions.append(candidate+site['target_delta'])
            if len(positions) > 1:
                return None
    return positions[0] if len(positions) == 1 else None


def discover(text, sections, symbols, site):
    found = set()
    for pattern in [site]+[dict(site, **variant, alternatives=[]) for variant in site.get('alternatives', [])]:
        address = discover_pattern(text, sections, symbols, pattern)
        if address is not None:
            found.add(address)
    return next(iter(found)) if len(found) == 1 else None


def verify_collection(path, catalog=None):
    data = Path(path).read_bytes()
    entries = images(data)
    catalog = json.loads(CATALOG.read_text()) if catalog is None else catalog
    results = []
    for owner, bundle in BUNDLES.items():
        text, sections, symbols = image(data, entries[bundle])
        for site in catalog:
            if site['owner'] != owner:
                continue
            address = discover(text, sections, symbols, site)
            results.append({'image': owner, 'reference': site['reference'],
                            'resolved': address, 'supported': address is not None})
    return {'schema': 1, 'collection_sha256': hashlib.sha256(data).hexdigest(),
            'catalog_sha256': hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
            'supported': bool(results) and all(row['supported'] for row in results),
            'sites': results}


def generate_header(catalog=None):
    catalog = json.loads(CATALOG.read_text()) if catalog is None else catalog
    lines = ['#pragma once', '#include "KernelSiteLocator.hpp"',
             '// Audited instruction-family contracts. Regenerate only after semantic review.',
             'namespace RaphaelKernelSites {']
    def literal(site, name, alternatives='nullptr', count=0):
        return '    {%d, %#x, %s, %d, %d, %s_bytes, %s_mask, sizeof(%s_bytes), %s, %s, %d, %s},' % (
            {'HWLibs': 0, 'FB': 1, 'X6000': 2}[site['owner']], site['reference'],
            json.dumps(site['symbol']) if site['symbol'] else 'nullptr',
            site['symbol_delta'], site['target_delta'], name, name, name,
            'true' if site.get('section') == '__const' else 'false', alternatives, count,
            json.dumps(site['scope_end_symbol']) if site.get('scope_end_symbol') else 'nullptr')
    for index, site in enumerate(catalog):
        patterns = [('site%d' % index, site)]+[
            ('site%d_alt%d' % (index, n), dict(site, **variant))
            for n, variant in enumerate(site.get('alternatives', []))]
        for name, pattern in patterns:
            for key in ('bytes', 'mask'):
                values = ','.join('0x'+pattern[key][n:n+2] for n in range(0, len(pattern[key]), 2))
                lines.append('static const uint8_t %s_%s[] = {%s};' % (name, key, values))
        if len(patterns) > 1:
            lines.append('static const Site site%d_alternatives[] = {' % index)
            lines.extend(literal(pattern, name) for name, pattern in patterns[1:])
            lines.append('};')
    lines.append('static const Site catalog[] = {')
    for index, site in enumerate(catalog):
        count = len(site.get('alternatives', []))
        lines.append(literal(site, 'site%d' % index,
                             'site%d_alternatives' % index if count else 'nullptr', count))
    return '\n'.join(lines+['};', '}'])+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--generate-header', type=Path)
    args = parser.parse_args()
    if args.generate_header:
        args.generate_header.write_text(generate_header())
    if args.collection:
        result = verify_collection(args.collection)
        output = json.dumps(result, indent=2)+'\n'
        if args.output:
            args.output.write_text(output)
        else:
            print(output, end='')
        return 0 if result['supported'] else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
