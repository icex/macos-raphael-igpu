#!/usr/bin/env python3
"""Generate the reviewed userspace instruction-family catalog (no image/build allowlist)."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT/'findings/research/update-portability-20261013/userspace-sites.json'


def generate_header(rows=None):
    rows = json.loads(CATALOG.read_text()) if rows is None else rows
    lines = ['#pragma once', '#include "KernelSiteLocator.hpp"', 'namespace RaphaelUserSites {']
    for index, row in enumerate(rows):
        patterns = [('user%d' % index, row)]+[
            ('user%d_alt%d' % (index, n), dict(row, **variant))
            for n, variant in enumerate(row.get('alternatives', []))]
        for name, pattern in patterns:
            if (not pattern['bytes'] or len(pattern['bytes']) != len(pattern['mask']) or
                    pattern['target_delta']+row['instruction_size'] > len(pattern['bytes'])//2):
                raise ValueError('invalid userspace instruction contract')
            for key in ('bytes', 'mask'):
                values = ','.join('0x'+pattern[key][n:n+2] for n in range(0, len(pattern[key]), 2))
                lines.append('static const uint8_t %s_%s[] = {%s};' % (name, key, values))
        if len(patterns) > 1:
            lines.append('static const RaphaelKernelSites::Site user%d_alternatives[] = {' % index)
            for name, pattern in patterns[1:]:
                lines.append('    {0, 0, nullptr, 0, %d, %s_bytes, %s_mask, sizeof(%s_bytes)},' %
                             (pattern['target_delta'], name, name, name))
            lines.append('};')
        suffix = ', false, user%d_alternatives, %d' % (index, len(patterns)-1) if len(patterns)>1 else ''
        lines.append('static const RaphaelKernelSites::Site %s {0, 0, nullptr, 0, %d, user%d_bytes, user%d_mask, sizeof(user%d_bytes)%s};' %
                     (row['name'].replace('-', '_'), row['target_delta'], index, index, index, suffix))
    return '\n'.join(lines+['}'])+'\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate-header', type=Path, required=True)
    args = parser.parse_args()
    args.generate_header.write_text(generate_header())
