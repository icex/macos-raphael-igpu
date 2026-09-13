#!/usr/bin/env python3
"""Decode rgpuhangdump=1 (XD:) serial lines into PM4 packets.

Reads a serial capture, groups each dump's dword windows by label (ring, IB1,
IB2, CE_IB1, IB1@BASE), finds the packet alignment that parses the longest
chain of valid PM4 headers, and names register writes with the Linux
gc_10_3_0_offset.h table.
"""
import argparse
import re
from pathlib import Path

NVD = Path('/home/bogdan/macos-vm/ref/linux/gc1036/nvd.h')
OFFSETS = Path('/home/bogdan/macos-vm/ref/linux/gc1036/asic_reg/gc_10_3_0_offset.h')
SEGMENTS = (0x1260, 0xa000, 0x1c000, 0x2400)
REG_STARTS = {  # PACKET3_SET_*_REG_START (dword indices), nvd.h
    0x68: ('CONFIG', 0x2000), 0x69: ('CONTEXT', 0xa000), 0x6a: ('CONTEXT', 0xa000),
    0x76: ('SH', 0x2c00), 0x77: ('SH', 0x2c00), 0x79: ('UCONFIG', 0xc000),
    0x7a: ('UCONFIG', 0xc000),
}
LINE = re.compile(r'XD: (?P<label>[A-Za-z0-9_@]+) vmid=(?P<vmid>\d+) \[(?P<index>0x[0-9a-f]+|0)\]'
                  r'(?P<words>(?: (?:[0-9a-f]{8}|--------))+)\s*$')
DUMP = re.compile(r'XD: gfx hang dump (\d+) (?:at|memory)')


def opcodes():
    names = {}
    for match in re.finditer(r'#define\s+PACKET3_([A-Z0-9_]+)\s+(0x[0-9A-Fa-f]{2})\s*$',
                             NVD.read_text(), re.M):
        names.setdefault(int(match.group(2), 16), match.group(1))
    return names


def registers():
    text = OFFSETS.read_text()
    offsets = dict((m.group(1), int(m.group(2), 0)) for m in
                   re.finditer(r'#define\s+mm([A-Za-z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)\s*$', text, re.M))
    names = {}
    for name, offset in offsets.items():
        if name.endswith('_BASE_IDX'):
            continue
        base = offsets.get(name + '_BASE_IDX')
        if base is None or base >= len(SEGMENTS):
            continue
        names.setdefault(SEGMENTS[base] + offset, name)
    return names


def parse(path):
    dumps = {}
    current = None
    for raw in Path(path).read_text(errors='replace').splitlines():
        if ' d' in raw and re.search(r'@ d\d{3}\| ', raw):
            continue  # deferred replay copies
        match = DUMP.search(raw)
        if match:
            current = int(match.group(1))
            dumps.setdefault(current, {'lines': [], 'windows': {}})
        if current is None or 'XD: ' not in raw:
            continue
        dumps[current]['lines'].append(raw.split('XD: ', 1)[1])
        match = LINE.search(raw)
        if not match:
            continue
        key = (match.group('label'), int(match.group('vmid')))
        window = dumps[current]['windows'].setdefault(key, {})
        index = int(match.group('index'), 16)
        for offset, word in enumerate(match.group('words').split()):
            if word != '--------':
                window[index + offset] = int(word, 16)
    return dumps


def valid_header(word, names):
    kind = word >> 30
    if word == 0x80000000:
        return 1
    if kind == 3 and (word & 0xff) in (0, 1, 2) and ((word >> 8) & 0xff) in names:
        if ((word >> 16) & 0x3fff) == 0x3fff and ((word >> 8) & 0xff) == 0x10:
            return 1  # PACKET3(NOP, 0x3fff) is a single-dword filler
        return ((word >> 16) & 0x3fff) + 2
    return 0


def chain(words, start, end, names):
    at, count = start, 0
    while at < end and at in words:
        size = valid_header(words[at], names)
        if size == 0:
            break
        at += size
        count += 1
    return count, at


def decode(words, names, regs, wrap=None):
    if not words:
        return []
    indices = sorted(words)
    first, end = indices[0], indices[-1] + 1
    contiguous = {i: words[i] for i in range(first, end) if i in words}
    # Prefer the alignment whose packet chain reaches furthest, then the earliest start.
    best = max(((chain(contiguous, s, end, names), s) for s in range(first, min(first + 32, end))),
               key=lambda item: (item[0][1], -item[1]))
    (_, _), start = best
    out = []
    at = start
    while at < end and at in contiguous:
        word = contiguous[at]
        size = valid_header(word, names)
        if size == 0:
            out.append(f'  [{at:#x}] {word:08x} ?? (alignment lost)')
            at += 1
            continue
        if size == 1:
            out.append(f'  [{at:#x}] {"PACKET2" if word == 0x80000000 else "NOP"}')
            at += 1
            continue
        opcode = (word >> 8) & 0xff
        body = [contiguous.get(at + 1 + i) for i in range(size - 1)]
        text = ' '.join('--------' if value is None else f'{value:08x}' for value in body)
        line = f'  [{at:#x}] {names[opcode]}({size - 1}) {text}'
        if opcode in REG_STARTS and body and body[0] is not None:
            kind, base = REG_STARTS[opcode]
            reg = base + (body[0] & 0xffff)
            labels = [regs.get(reg + i, f'{reg + i:#x}') for i in range(len(body) - 1)]
            line += '  <- ' + ', '.join(f'{label}={value:#x}' if value is not None else label
                                         for label, value in zip(labels, body[1:]))
        out.append(line)
        at += size
    if start != first:
        out.insert(0, f'  (aligned at {start:#x}; {start - first} leading dwords skipped)')
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial')
    args = parser.parse_args()
    names, regs = opcodes(), registers()
    for number, dump in sorted(parse(args.serial).items()):
        print(f'== dump {number} ==')
        for line in dump['lines']:
            if not LINE.search('XD: ' + line):
                print('  ' + line)
        for (label, vmid), words in dump['windows'].items():
            print(f'-- {label} vmid={vmid} ({len(words)} dwords)')
            for line in decode(words, names, regs):
                print(line)


if __name__ == '__main__':
    main()
