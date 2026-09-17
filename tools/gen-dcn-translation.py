#!/usr/bin/env python3
"""Generate the DCN 3.0.2 -> DCN 3.1.5 register translation tables.

Apple's display core is built for DCN 3.02 (Navi 23). Raphael is DCN 3.1.5.
Both use the same DCN/DPCS base segments, and about 94% of the registers the
two maps share keep their dword index; the rest moved or no longer exist. This
tool matches registers by name in the Linux offset headers and emits sorted
C++ tables consumed by src/DcnTranslation.hpp:

  * moved   - the name exists in both maps at different indices -> rewrite
  * removed - the name exists only in 3.0.2                     -> drop the access
  * same    - identical index                                    -> no entry

Several names can share one 3.0.2 index (indirect/alias registers). They are
grouped; a group is only rewritten when every surviving name agrees on one
3.1.5 index, otherwise it is reported as ambiguous and left untranslated.

Two semantic corrections override the name match:

  * Power domains. 3.0.2 gates HUBP i with DOMAIN 2i and DPP i with DOMAIN 2i+1;
    3.1.5 gates the whole pipe i with DOMAIN i and has no DPP domain. DOMAIN 2i
    maps to DOMAIN i (i < 4) and every other DOMAIN0..9 register is dropped.
  * Moved fields. Registers present in both maps whose fields moved (for example
    ODMx_OPTC_DATA_SOURCE_SELECT) get a field permutation entry.

    tools/gen-dcn-translation.py --linux-src ~/src/ref/linux --output src/DcnTranslationTable.hpp
"""
import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

BASES = (0x00000012, 0x000000C0, 0x000034C0, 0x00009000, 0x02403C00, 0)
PAIRS = (
    ('dcn', 'dcn_3_0_2', 'dcn_3_1_5'),
    ('dpcs', 'dpcs_3_0_0', 'dpcs_4_2_2'),
)
HEADER_ROOT = 'drivers/gpu/drm/amd/include/asic_reg'
REGISTER = re.compile(r'#define\s+(?:reg|mm)(\w+)\s+(0x[0-9a-fA-F]+)\s*\n'
                      r'#define\s+(?:reg|mm)\1_BASE_IDX\s+(\d+)')
DOMAIN = re.compile(r'^DOMAIN(\d+)_PG_(CONFIG|STATUS)$')
KIND_MOVE, KIND_DROP = 0, 1
# Named indices the plugin handles specially: (constant, header version, register name).
NAMED = (
    ('k302DmcubCntl', 'old', 'DMCUB_CNTL'),
    ('k315DmcubCntl2', 'new', 'DMCUB_CNTL2'),
    ('k315DmcubScratch0', 'new', 'DMCUB_SCRATCH0'),
    ('k315DmcubScratch15', 'new', 'DMCUB_SCRATCH15'),
    ('k315DcIpRequestCntl', 'new', 'DC_IP_REQUEST_CNTL'),
    ('k315Domain0PgConfig', 'new', 'DOMAIN0_PG_CONFIG'),
    ('k315OtgPixelRateCntl0', 'new', 'OTG0_PIXEL_RATE_CNTL'),
    ('k315DentistDispclkCntl', 'new', 'DENTIST_DISPCLK_CNTL'),
)


def load_offsets(path):
    text = path.read_text()
    return text, {m.group(1): BASES[int(m.group(3))] + int(m.group(2), 16)
                  for m in REGISTER.finditer(text)}


def load_fields(path):
    text = path.read_text()
    shifts = {(m.group(1), m.group(2)): int(m.group(3), 16) for m in re.finditer(
        r'#define\s+([A-Z0-9_]+?)__([A-Z0-9_]+)__SHIFT\s+(0x[0-9a-fA-F]+)', text)}
    fields = defaultdict(dict)
    for m in re.finditer(r'#define\s+([A-Z0-9_]+?)__([A-Z0-9_]+)_MASK\s+(0x[0-9a-fA-F]+)L?', text):
        key = (m.group(1), m.group(2))
        if key in shifts:
            fields[key[0]][key[1]] = (shifts[key], int(m.group(3), 16))
    return fields


def layout(fields, name):
    """Instance registers (ODM0_OPTC_DATA_SOURCE_SELECT) share their type's field names."""
    return fields.get(name) or fields.get(re.sub(r'^[A-Z]+\d+_', '', name), {})


def domain_override(name, new):
    match = DOMAIN.match(name)
    if not match or int(match.group(1)) > 9:
        return None
    index = int(match.group(1))
    if index % 2 or index // 2 > 3:
        return ('drop', None)
    target = f'DOMAIN{index // 2}_PG_{match.group(2)}'
    return ('move', new[target]) if target in new else ('drop', None)


def field_remap(old_layout, new_layout):
    """Fields present in both layouts, as (src shift, width, dst shift); None if nothing moved."""
    moved, fields = False, []
    for field, (shift, mask) in sorted(old_layout.items(), key=lambda f: f[1][0]):
        if field not in new_layout:
            continue
        new_shift, new_mask = new_layout[field]
        if new_shift != shift:
            moved = True
        width = min(bin(mask).count('1'), bin(new_mask).count('1'))
        fields.append((shift, width, new_shift))
    return fields if moved else None


def build(linux_src):
    moves, drops, ambiguous, digests, remaps, named = {}, {}, {}, {}, {}, {}
    for sub, old_name, new_name in PAIRS:
        root = Path(linux_src) / HEADER_ROOT / sub
        old_text, old = load_offsets(root / f'{old_name}_offset.h')
        new_text, new = load_offsets(root / f'{new_name}_offset.h')
        digests[f'{old_name}_offset.h'] = hashlib.sha256(old_text.encode()).hexdigest()
        digests[f'{new_name}_offset.h'] = hashlib.sha256(new_text.encode()).hexdigest()
        if sub == 'dcn':
            old_fields = load_fields(root / f'{old_name}_sh_mask.h')
            new_fields = load_fields(root / f'{new_name}_sh_mask.h')
            for constant, version, register in NAMED:
                named[constant] = (old if version == 'old' else new)[register]
        by_index = defaultdict(list)
        for name, index in old.items():
            by_index[index].append(name)
        for index, names in by_index.items():
            label = sorted(names)[0]
            override = domain_override(label, new) if sub == 'dcn' and len(names) == 1 else None
            if override:
                if override[0] == 'drop':
                    drops.setdefault(index, label)
                elif override[1] != index:
                    moves.setdefault(index, (override[1], label + ' (pipe domain)'))
                continue
            targets = {new[n] for n in names if n in new}
            if not targets:
                drops.setdefault(index, label)
                continue
            if len(targets) > 1:
                ambiguous[index] = sorted(names)
                continue
            target = targets.pop()
            if target != index:
                moves.setdefault(index, (target, label))
            if sub == 'dcn' and len(names) == 1:
                remap = field_remap(layout(old_fields, label), layout(new_fields, label))
                if remap:
                    remaps[index] = (label, remap)
    for index in list(drops):
        if index in moves:
            del drops[index]
    return moves, drops, ambiguous, digests, remaps, named


def render(moves, drops, ambiguous, digests, remaps, named):
    entries = sorted([(i, t, KIND_MOVE, n) for i, (t, n) in moves.items()] +
                     [(i, 0, KIND_DROP, n) for i, n in drops.items()])
    lines = [
        '// Generated by tools/gen-dcn-translation.py -- do not edit.',
        '// DCN 3.0.2 / DPCS 3.0.0 register index -> DCN 3.1.5 / DPCS 4.2.2 index.',
    ]
    for name, digest in sorted(digests.items()):
        lines.append(f'// {name} sha256 {digest}')
    lines += [
        f'// {len(moves)} moved, {len(drops)} removed, {len(ambiguous)} ambiguous (untranslated),',
        f'// {len(remaps)} with moved fields.',
        '#pragma once',
        '#include <stdint.h>',
        '',
        'namespace RaphaelDcn {',
        'enum : uint8_t { kXlatMove = 0, kXlatDrop = 1 };',
        'struct XlatEntry { uint32_t from; uint32_t to; uint8_t kind; };',
        'struct FieldMove { uint8_t fromShift; uint8_t width; uint8_t toShift; };',
        'struct FieldRemap { uint32_t from; uint8_t count; FieldMove fields[12]; };',
        '',
    ]
    for constant, index in named.items():
        lines.append(f'static constexpr uint32_t {constant} = {index:#08x};')
    lines += ['', 'static const XlatEntry kDcn302To315[] = {']
    for index, target, kind, name in entries:
        lines.append(f'    {{{index:#08x}, {target:#08x}, {kind}}},  // {name}')
    lines += ['};', '',
              '// Keyed by the 3.0.2 index; fields are listed in 3.0.2 bit order.',
              'static const FieldRemap kDcn302FieldRemaps[] = {']
    for index, (label, fields) in sorted(remaps.items()):
        if len(fields) > 12:
            raise SystemExit(f'{label}: {len(fields)} fields exceed the table width')
        body = ', '.join(f'{{{s}, {w}, {d}}}' for s, w, d in fields)
        lines.append(f'    {{{index:#08x}, {len(fields)}, {{{body}}}}},  // {label}')
    lines += ['};', '}  // namespace RaphaelDcn', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--linux-src', type=Path, default=Path.home() / 'src/ref/linux')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', action='store_true', help='print ambiguous groups and remaps')
    args = parser.parse_args()
    moves, drops, ambiguous, digests, remaps, named = build(args.linux_src)
    args.output.write_text(render(moves, drops, ambiguous, digests, remaps, named))
    print(f'{len(moves)} moved, {len(drops)} removed, {len(ambiguous)} ambiguous, '
          f'{len(remaps)} field remaps -> {args.output}')
    if args.report:
        for index, names in sorted(ambiguous.items()):
            print(f'  ambiguous {index:#x}: {", ".join(names)}')
        for index, (label, fields) in sorted(remaps.items()):
            print(f'  remap {index:#x} {label}: {fields}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
