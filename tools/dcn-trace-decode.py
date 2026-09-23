#!/usr/bin/env python3
"""Decode RaphaelGPU 'DCN: R/W' trace lines with DCN 3.1.5 register names and fields.

    tools/dcn-trace-decode.py ~/macos-vm/run/serial.log --match 'DC_I2C|DC_GPIO_DDC1|AUX_CTRL_5'
"""
import argparse, importlib.util, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('probe', HERE / 'dcn-state-probe.py')
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)
LINE = re.compile(r'DCN: (R|W) 0x([0-9a-f]+) (=|->|DROP) 0x([0-9a-f]+) v=0x([0-9a-f]+) n=(\d+) @(0x[0-9a-f]+)<(0x[0-9a-f]+)<(0x[0-9a-f]+)')

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('log', type=Path); p.add_argument('--linux-src', type=Path, default=probe.DEFAULT_LINUX)
    p.add_argument('--match', default='.', help='regex on the 3.1.5 register name')
    p.add_argument('--after', default='', help='only lines after the first line containing this text')
    a = p.parse_args()
    r315, f315 = probe.parse_headers(a.linux_src, '3_1_5'); r302, _ = probe.parse_headers(a.linux_src, '3_0_2')
    by315 = {probe.DCN_BASE[b] + r: n for n, (b, r) in r315.items()}
    by302 = {probe.DCN_BASE[b] + r: n for n, (b, r) in r302.items()}
    want = re.compile(a.match); started = not a.after
    for line in a.log.read_text(errors='replace').splitlines():
        if not started:
            started = a.after in line; continue
        m = LINE.search(line)
        if not m: continue
        op, src, kind, dst, val, n, ret, up1, up2 = m.groups()
        name = by302.get(int(src, 16)) if kind == 'DROP' else by315.get(int(dst, 16), by302.get(int(src, 16), f'?{dst}'))
        if not name or not want.search(name): continue
        v = int(val, 16); layout = probe.field_layout(f315, name) if kind != 'DROP' else None
        fields = ' '.join(f'{k}={x:#x}' for k, x in probe.decode(v, layout or []).items() if x)
        print(f'{op} {name:32s} {v:#10x} n={n:>3s} @{ret}<{up1}<{up2}  {fields}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
