#!/usr/bin/env python3
"""Read Raphael display-engine (DCN 3.1.5) registers over user-owned VFIO.

Reads only: no register is written, no SMU message is sent. It answers the
questions a guest display port needs first -- is a sink present on each HPD
pin, is the DMCUB microcontroller running, which OTG/DIG/DCCG blocks are live,
and which power domains are gated -- without booting the guest.

Register names, BASE_IDX values and field layouts come from the Linux
`dcn_3_1_5_offset.h` / `dcn_3_1_5_sh_mask.h` headers (see --linux-src). The DCN
base segments are Raphael's (dcn315_resource.c), identical to Navi 2x.

    tools/dcn-state-probe.py                       # default register set
    tools/dcn-state-probe.py --regs '^HPD\\d_' --json out.json
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

DCN_BASE = (0x00000012, 0x000000C0, 0x000034C0, 0x00009000, 0x02403C00)
DEFAULT_LINUX = Path.home() / 'src/ref/linux'
HEADER_DIR = 'drivers/gpu/drm/amd/include/asic_reg/dcn'
DEFAULT_REGS = (
    r'^HPD\d_DC_HPD_(INT_STATUS|CONTROL|INT_CONTROL)$',
    r'^DMCUB_(CNTL|CNTL2|STATUS|SCRATCH\d+|INBOX1_(RPTR|WPTR|SIZE)|OUTBOX1_(RPTR|WPTR)|'
    r'TIMER_CURRENT|MEM_CNTL|SEC_CNTL|UNDEFINED_ADDRESS_FAULT_ADDR)$',
    r'^OTG\d_OTG_(CONTROL|H_TOTAL|V_TOTAL|STATUS|STATUS_POSITION|CLOCK_CONTROL|BLANK_CONTROL)$',
    r'^DIG\d_(DIG_FE_CNTL|DIG_BE_CNTL|DIG_BE_EN_CNTL|HDMI_CONTROL|TMDS_CNTL)$',
    r'^DOMAIN\d+_PG_STATUS$',
    r'^(DCCG_GATE_DISABLE_CNTL\d?|OTG_PIXEL_RATE_CNTL\d|SYMCLK[A-E]_CLOCK_ENABLE|'
    r'PHY[A-E]SYMCLK_CLOCK_CNTL|DPPCLK_CTRL|DENTIST_DISPCLK_CNTL|DCCG_AUDIO_DTO_SOURCE)$',
    r'^(HUBP\d_HUBP_CLK_CNTL|HUBPREQ\d_DCSURF_PRIMARY_SURFACE_ADDRESS)$',
    r'^(DC_I2C_(CONTROL|STATUS|ARBITRATION)|DIO_LINK[A-F]_CNTL|DC_GPIO_HPD_(A|EN|Y|MASK))$',
    r'^(DC_IP_REQUEST_CNTL|DMU_CLK_CNTL|DCFCLK_CNTL|DIO_CLK_CNTL\d?)$',
)


def _load_vfio():
    path = Path(__file__).with_name('vfio-recover.py')
    spec = importlib.util.spec_from_file_location('vfio_recover_host', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_headers(linux_src, version='3_1_5'):
    base = Path(linux_src) / HEADER_DIR
    offsets = (base / f'dcn_{version}_offset.h').read_text()
    masks = (base / f'dcn_{version}_sh_mask.h').read_text()
    regs = {m.group(1): (int(m.group(3)), int(m.group(2), 16)) for m in re.finditer(
        r'#define\s+(?:reg|mm)(\w+)\s+(0x[0-9a-fA-F]+)\s*\n#define\s+(?:reg|mm)\1_BASE_IDX\s+(\d+)',
        offsets)}
    # The headers list every __SHIFT of a register before its _MASK lines.
    shifts = {(m.group(1), m.group(2)): int(m.group(3), 16) for m in re.finditer(
        r'#define\s+([A-Z0-9_]+?)__([A-Z0-9_]+)__SHIFT\s+(0x[0-9a-fA-F]+)', masks)}
    fields = {}
    for m in re.finditer(r'#define\s+([A-Z0-9_]+?)__([A-Z0-9_]+)_MASK\s+(0x[0-9a-fA-F]+)L?', masks):
        key = (m.group(1), m.group(2))
        if key in shifts:
            fields.setdefault(key[0], []).append((key[1], shifts[key], int(m.group(3), 16)))
    return regs, fields


def bar5_offset(base_idx, reg):
    return (DCN_BASE[base_idx] + reg) * 4


def select(regs, patterns):
    compiled = [re.compile(p) for p in patterns]
    return sorted(name for name in regs if any(p.search(name) for p in compiled))


def field_layout(fields, name):
    """Instance registers (OTG0_OTG_CONTROL) share their type's field names (OTG_CONTROL)."""
    if name in fields:
        return fields[name]
    generic = re.sub(r'^[A-Z]+\d+_', '', name)
    return fields.get(generic)


def decode(value, layout):
    return {name: (value & mask) >> shift for name, shift, mask in layout}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--linux-src', type=Path, default=DEFAULT_LINUX)
    parser.add_argument('--regs', action='append', help='register-name regex (repeatable)')
    parser.add_argument('--json', type=Path, help='also write the result here')
    parser.add_argument('--raw', action='store_true', help='omit decoded fields')
    args = parser.parse_args()

    R = _load_vfio()
    if R.active_qemu():
        raise SystemExit('refusing: a QEMU process is running and owns the device')
    regs, fields = parse_headers(args.linux_src)
    names = select(regs, args.regs or DEFAULT_REGS)
    result = {'boot_id': R.current_boot_id(), 'registers': {}}
    with R.LegacyVfio() as mmio:
        size = len(mmio.bar)
        for name in names:
            base_idx, reg = regs[name]
            offset = bar5_offset(base_idx, reg)
            if offset + 4 > size:
                result['registers'][name] = {'error': f'offset {offset:#x} outside BAR5'}
                continue
            value = mmio.read32(offset)
            entry = {'bar5': f'{offset:#07x}', 'value': f'{value:#010x}'}
            layout = field_layout(fields, name)
            if not args.raw and layout and value != 0xffffffff:
                entry['fields'] = {k: v for k, v in decode(value, layout).items() if v}
            result['registers'][name] = entry
    text = json.dumps(result, indent=1)
    if args.json:
        args.json.write_text(text + '\n')
    for name, entry in result['registers'].items():
        extra = ' '.join(f'{k}={v:#x}' for k, v in entry.get('fields', {}).items())
        print(f"{name:45s} {entry.get('value', entry.get('error'))} {extra}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
