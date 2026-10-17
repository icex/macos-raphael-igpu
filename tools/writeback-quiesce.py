"""Stop a leftover iGPU display writeback and close its AGP window before a reset.

Candidates with rgpuwbdisplay program DCN writeback (DWB + MCIF_WB) to DMA every
frame through an MMHUB/DCHUBBUB AGP window. If the guest or QEMU dies without
stopping it, the display engine keeps that state across QEMU exit and MODE2, and
the next guest would re-enable bus mastering with writeback still streaming into
a memory system it is reprogramming. Run this with bus mastering still off (the
device is idle after vfio close), before every MODE2 reset.

Register writes only: DWB/MCIF_WB enable bits, the MPC DWB mux, and AGP/system
aperture values that carry this project's own AGP signature. Nothing else, and
never DMCUB. DCN 3.1.5 dword indices are identical to src/WritebackDisplay.hpp.
"""

FC_MODE_CTRL = 0x66ea          # FC_FRAME_CAPTURE_EN bit 0
MCIF_SW_CONTROL = 0x3732       # MCIF_WB_BUFMGR_ENABLE bit 0
DWB_ENABLE_CLK_CTRL = 0x66e8   # DWB_ENABLE bit 0
MPC_DWB0_MUX = 0x955c          # MUX [3:0], 0xf = off
MM_FB_TOP = 0x1a8ed
MM_AGP_TOP, MM_AGP_BOT, MM_AGP_BASE = 0x1a8ee, 0x1a8ef, 0x1a8f0
MM_SYS_HIGH = 0x1a8f2
DCN_AGP_BOT, DCN_AGP_TOP, DCN_AGP_BASE = 0x3938, 0x3939, 0x393a
SDMA0_RLC0_RB_CNTL, SDMA0_RLC0_IB_CNTL = 0x1390, 0x139a   # our SDMA copy queue (GC seg0 0x1260)
GC_AGP_TOP, GC_AGP_BOT, GC_AGP_BASE, GC_SYS_HIGH, GC_FB_TOP = 0x295e, 0x295f, 0x2960, 0x2962, 0x295d
WRITEBACK_GPA = 0x4000000000   # QEMU x-rgpu-display region; AGP base signature
AGP_SIGNATURE = WRITEBACK_GPA >> 24


def quiesce(read32, write32):
    """read32/write32 take BAR5 byte offsets. Returns a receipt dict."""
    reg = lambda index: read32(index * 4)
    put = lambda index, value: write32(index * 4, value & 0xffffffff)
    before = {name: reg(index) for name, index in (
        ('FC_MODE_CTRL', FC_MODE_CTRL), ('MCIF_SW_CONTROL', MCIF_SW_CONTROL),
        ('DWB_ENABLE_CLK_CTRL', DWB_ENABLE_CLK_CTRL), ('MPC_DWB0_MUX', MPC_DWB0_MUX),
        ('MM_FB_TOP', MM_FB_TOP), ('MM_AGP_BOT', MM_AGP_BOT), ('MM_AGP_TOP', MM_AGP_TOP),
        ('MM_AGP_BASE', MM_AGP_BASE), ('MM_SYS_HIGH', MM_SYS_HIGH),
        ('DCN_AGP_BOT', DCN_AGP_BOT), ('DCN_AGP_TOP', DCN_AGP_TOP),
        ('DCN_AGP_BASE', DCN_AGP_BASE))}
    receipt = {'schema': 1, 'before': before, 'actions': []}
    if any(value == 0xffffffff for value in before.values()):
        receipt['error'] = 'register read returned all ones; nothing written'
        return receipt
    if before['FC_MODE_CTRL'] & 1:
        put(FC_MODE_CTRL, before['FC_MODE_CTRL'] & ~1); receipt['actions'].append('fc_capture_off')
    if before['MCIF_SW_CONTROL'] & 1:
        put(MCIF_SW_CONTROL, before['MCIF_SW_CONTROL'] & ~1); receipt['actions'].append('mcif_bufmgr_off')
    if before['DWB_ENABLE_CLK_CTRL'] & 1:
        put(DWB_ENABLE_CLK_CTRL, before['DWB_ENABLE_CLK_CTRL'] & ~1); receipt['actions'].append('dwb_off')
    if before['MPC_DWB0_MUX'] & 0xf != 0xf:
        put(MPC_DWB0_MUX, (before['MPC_DWB0_MUX'] & ~0xf) | 0xf); receipt['actions'].append('dwb_mux_off')
    if before['MM_AGP_BASE'] == AGP_SIGNATURE:
        put(MM_AGP_BASE, 0); put(MM_AGP_BOT, 0xffffff); put(MM_AGP_TOP, 0)
        fb_high = (((before['MM_FB_TOP'] & 0xffffff) << 24) | 0xffffff) >> 18
        if before['MM_FB_TOP'] and before['MM_SYS_HIGH'] > fb_high:
            put(MM_SYS_HIGH, fb_high); receipt['actions'].append('mmhub_sys_aperture_restored')
        receipt['actions'].append('mmhub_agp_closed')
    rlc0, rlc0ib = reg(SDMA0_RLC0_RB_CNTL), reg(SDMA0_RLC0_IB_CNTL)
    receipt['before']['SDMA0_RLC0_RB_CNTL'] = rlc0
    if rlc0 != 0xffffffff and rlc0 & 1:
        put(SDMA0_RLC0_RB_CNTL, rlc0 & ~1); receipt['actions'].append('sdma_rlc0_rb_off')
    if rlc0ib != 0xffffffff and rlc0ib & 1:
        put(SDMA0_RLC0_IB_CNTL, rlc0ib & ~1); receipt['actions'].append('sdma_rlc0_ib_off')
    if reg(GC_AGP_BASE) == AGP_SIGNATURE:
        put(GC_AGP_BASE, 0); put(GC_AGP_BOT, 0xffffff); put(GC_AGP_TOP, 0)
        fb_top = reg(GC_FB_TOP)
        fb_high = (((fb_top & 0xffffff) << 24) | 0xffffff) >> 18
        if fb_top and reg(GC_SYS_HIGH) > fb_high:
            put(GC_SYS_HIGH, fb_high)
        receipt['actions'].append('gc_agp_closed')
    if before['DCN_AGP_BASE'] == AGP_SIGNATURE:
        put(DCN_AGP_BASE, 0); put(DCN_AGP_BOT, 0); put(DCN_AGP_TOP, 0)
        receipt['actions'].append('dcn_agp_closed')
    receipt['after'] = {name: reg(index) for name, index in (
        ('FC_MODE_CTRL', FC_MODE_CTRL), ('MCIF_SW_CONTROL', MCIF_SW_CONTROL),
        ('DWB_ENABLE_CLK_CTRL', DWB_ENABLE_CLK_CTRL), ('MPC_DWB0_MUX', MPC_DWB0_MUX),
        ('MM_AGP_BASE', MM_AGP_BASE), ('MM_SYS_HIGH', MM_SYS_HIGH), ('DCN_AGP_BASE', DCN_AGP_BASE))}
    a = receipt['after']
    a['SDMA0_RLC0_RB_CNTL'] = reg(SDMA0_RLC0_RB_CNTL)
    a['GC_AGP_BASE'] = reg(GC_AGP_BASE)
    receipt['quiet'] = (not a['SDMA0_RLC0_RB_CNTL'] & 1 and a['GC_AGP_BASE'] != AGP_SIGNATURE and
                        not a['FC_MODE_CTRL'] & 1 and not a['MCIF_SW_CONTROL'] & 1 and
                        not a['DWB_ENABLE_CLK_CTRL'] & 1 and a['MM_AGP_BASE'] != AGP_SIGNATURE and
                        a['DCN_AGP_BASE'] != AGP_SIGNATURE)
    return receipt
