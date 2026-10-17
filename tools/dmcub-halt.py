"""Halt the host's still-running DMCUB display firmware before the first guest of a boot.

After a fresh host boot the iGPU's DMCUB keeps running the firmware amdgpu loaded; the
guest's plug-free display path (rgpuvirtualsink + rgpudcncold) only accepts the state a
host suspend/resume leaves behind: processor in reset, no version, and empty code windows
and regions (src/ConsoleTmrSafety.hpp emptyFirmware/holdEmptyFirmware). This reproduces
Linux dmub_dcn31_reset (GPINT STOP_FW, wait for ACK, the 0xDEADDEAD response and PWAIT,
then soft reset, DMUIF reset, ENABLE clear, mailbox pointers and SCRATCH0 cleared, GPINT
cleared) and then clears the window/region registers and SCRATCH1 so that the guest sees
exactly that empty state.

Register writes only, with bus mastering off: no firmware is loaded, started or
released from reset, and PSP/SMU are not touched. Indices are DCN 3.1.5 dword offsets
into BAR5 (seg2 base included).
"""

SCRATCH0, SCRATCH1, SCRATCH7 = 0x36a3, 0x36a4, 0x36aa
CNTL, CNTL2 = 0x36b6, 0x36c0
GPINT_DATAIN1, TIMER_CURRENT = 0x36b8, 0x36bd
MMHUBBUB_SOFT_RESET = 0x3802
INBOX1_RPTR, INBOX1_WPTR = 0x3697, 0x3696
OUTBOX1_RPTR, OUTBOX1_WPTR = 0x369f, 0x369e
OUTBOX0_RPTR, OUTBOX0_WPTR = 0x369b, 0x369a
CW_REGS = (0x3665, 0x3666, 0x366d, 0x366e, 0x3675, 0x3676, 0x3677, 0x3678)
REGION_REGS = (0x364e, 0x364f, 0x3650, 0x3651, 0x3652, 0x3653, 0x365e, 0x365f, 0x3660)
ENABLE, PWAIT = 0x10000, 0x100000
LINUX_IMAGE_VERSION = 0x05003500         # SCRATCH1 of the image amdgpu loads via PSP
DMUIF_RESET = 0x100
STOP_FW = (1 << 28) | (2 << 16)          # status=1, command STOP_FW, param 0
STOP_FW_ACKED = 2 << 16
STOP_FW_RESPONSE = 0xDEADDEAD
ACCEPTED_CNTL = (0, 0x80000, 0x90000)     # holdEmptyFirmware's observed set
HELD_CNTL = ACCEPTED_CNTL + (0x800c6, 0x900c6)   # + a halted platform image (observed 0x800c6)


def empty(read):
    """Mirror of RaphaelConsoleTmr::emptyFirmware."""
    return (read(SCRATCH0) == 0 and read(SCRATCH1) == 0 and read(CNTL2) == 1 and
            not any(read(r) for r in CW_REGS) and not any(read(r) for r in REGION_REGS))


def held(read):
    """Mirror of RaphaelConsoleTmr::heldLoadedFirmware: CPU in reset, ENABLE clear, DMUIF
    reset, boot status and regions cleared."""
    return ((read(CNTL) & ~PWAIT) in HELD_CNTL and read(CNTL2) & 1 == 1 and
            read(MMHUBBUB_SOFT_RESET) & DMUIF_RESET and read(SCRATCH0) == 0 and
            not any(read(r) for r in REGION_REGS))


def snapshot(read):
    names = dict(SCRATCH0=SCRATCH0, SCRATCH1=SCRATCH1, SCRATCH7=SCRATCH7, CNTL=CNTL,
                 CNTL2=CNTL2, GPINT_DATAIN1=GPINT_DATAIN1, TIMER=TIMER_CURRENT,
                 MMHUBBUB_SOFT_RESET=MMHUBBUB_SOFT_RESET)
    state = {k: read(v) for k, v in names.items()}
    state['windows'] = [read(r) for r in CW_REGS]
    state['regions'] = [read(r) for r in REGION_REGS]
    return state


def classify(read, sleep):
    s = snapshot(read)
    if any(v == 0xffffffff for v in (s['CNTL'], s['CNTL2'], s['MMHUBBUB_SOFT_RESET'])):
        return 'unreadable', s
    if empty(read):
        return 'empty', s
    t0 = read(TIMER_CURRENT); sleep(0.002); t1 = read(TIMER_CURRENT)
    s['timer_advancing'] = t1 != t0
    if not (s['CNTL2'] & 1) and (s['CNTL'] & ENABLE):
        return 'running', s
    if s['CNTL2'] & 1:
        return 'held-loaded', s
    return 'unknown', s


def admit(kind, state):
    """MODE2's cold-path admission (no writes): returns (receipt, error or None).

    empty: after a host suspend/resume. linux-image: the image amdgpu loaded through the PSP,
    still running on a fresh boot or held by a previous guest of this boot; the guest stops
    it itself and keeps its secure windows (RaphaelGPU.cpp coldLinuxImage). Every other
    state is refused, notably the platform's own image that amdgpu.virtual_display leaves
    in place: launching over it froze the host (481)."""
    version = state.get('SCRATCH1')
    linux_image = kind in ('running', 'held-loaded') and version == LINUX_IMAGE_VERSION
    receipt = {'kind': 'linux-image' if linux_image else kind, 'state': kind,
               'action': 'none', 'version': version}
    if kind == 'empty' or linux_image:
        return receipt, None
    return receipt, (f'DMCUB is {kind} with display firmware version {version or 0:#x}, not the '
                     'Linux driver image: boot without amdgpu.virtual_display; reset refused')


def halt(read, write, sleep, polls=1000):
    """Returns a receipt; 'empty_after' True means the guest cold path will accept it."""
    kind, before = classify(read, sleep)
    receipt = {'schema': 1, 'kind': kind, 'before': before, 'steps': []}
    if kind == 'empty':
        receipt['empty_after'] = True
        return receipt
    if kind not in ('running', 'held-loaded'):
        receipt['error'] = f'refusing unknown DMCUB state {kind}'
        receipt['empty_after'] = False
        return receipt
    if kind == 'running':
        write(GPINT_DATAIN1, STOP_FW)
        acked = response = pwait = False
        for _ in range(polls):
            if read(GPINT_DATAIN1) == STOP_FW_ACKED:
                acked = True; break
            sleep(0.0001)
        for _ in range(polls):
            if read(SCRATCH7) == STOP_FW_RESPONSE:
                response = True; break
            sleep(0.0001)
        for _ in range(polls):
            if read(CNTL) & PWAIT:
                pwait = True; break
            sleep(0.0001)
        receipt['steps'].append(dict(stop_fw_acked=acked, stop_fw_response=response, pwait=pwait))
    if read(CNTL) & ENABLE:
        write(CNTL2, read(CNTL2) | 1)
        write(MMHUBBUB_SOFT_RESET, read(MMHUBBUB_SOFT_RESET) | DMUIF_RESET)
        write(CNTL, read(CNTL) & ~ENABLE)
        receipt['steps'].append('soft-reset dmuif-reset enable-cleared')
    for reg in (INBOX1_RPTR, INBOX1_WPTR, OUTBOX1_RPTR, OUTBOX1_WPTR,
                OUTBOX0_RPTR, OUTBOX0_WPTR, SCRATCH0):
        write(reg, 0)
    write(GPINT_DATAIN1, 0)
    # The processor is held in reset: clear what a host resume leaves empty.
    if not (read(CNTL2) & 1):
        receipt['error'] = 'processor reset did not assert'
        receipt['empty_after'] = False
        return receipt
    for reg in CW_REGS + REGION_REGS + (SCRATCH1,):
        write(reg, 0)
    receipt['steps'].append('windows regions scratch1 cleared')
    after = snapshot(read)
    t0 = read(TIMER_CURRENT); sleep(0.002); after['timer_advancing'] = read(TIMER_CURRENT) != t0
    receipt['after'] = after
    receipt['empty_after'] = (empty(read) and (after['CNTL'] & ~PWAIT) in ACCEPTED_CNTL and
                              after['MMHUBBUB_SOFT_RESET'] in (0, DMUIF_RESET) and
                              not after['timer_advancing'])
    # Platform-loaded firmware (UEFI boot display through the PSP) keeps its window registers
    # locked, so it cannot be emptied; the guest cold path also accepts it held in reset
    # (src/ConsoleTmrSafety.hpp heldLoadedFirmware), because it never releases the CPU.
    receipt['held_after'] = held(read) and not after['timer_advancing']
    if not (receipt['empty_after'] or receipt['held_after']):
        receipt['error'] = 'state after halt does not match the guest cold-path contract'
    return receipt
