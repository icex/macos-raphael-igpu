# c447: DAL virtual (emulated) sink in AMDRadeonX6000Framebuffer 24G830

All addresses are offsets into the AMDRadeonX6000Framebuffer kext (fbBase-relative, the same space as kOffDcCreate=0xfea5e).
Sources: roadmap-24G830/AMDRadeonX6000Framebuffer-full/{all.c,functions/}, binaries/AMDRadeonX6000Framebuffer.
**V** = verified from decompile/disasm/raw bytes. **I** = inferred (Linux name or semantics).

## 1. Detection and EDID flow
- AmdRadeonController::detectAllDisplays 0x4dbaa / detectDisplayOnLink 0x4e36e -> AMDRadeonX6000_AmdLink::detectLink 0x45668 -> DalServices vtable+0x50 = **AmdDalServices::linkDetect 0x669be** (V). Apple-side detection has no HPD gate (only AmdLink flag +0x43). Apple AmdLinks come from the ATOM connector table (createLinks 0x4c42a, max 6), not from dc->link_count (V).
- linkDetect(reason, DetectedLinkStatus*): it calls **dc_link_detect 0x16f799**(link, reason!=0). Status: +0 link_index, +4 connected (= link->type!=0 and local_sink!=NULL), +8 sink signal, +0xc EDID len, +0x10 EDID copied from local_sink (0x400 bytes). If detect returns false and type!=MST, it returns 0xe00002c9 (V).
- dc_link_detect 0x16f799: if connector_signal is **0x200 or 0x400**, it returns false right away (V). Otherwise it calls detect_sink 0x16f51b (HPD GPIO; uses link+0x53 when ep_type link+0x1c0 != 0), dc_sink_create, dm_helpers_read_local_edid 0x74ad0->0x12f611, dm_helpers_parse_edid_caps 0x74ada (our "EDID bridge" hook) (V).
- dc_link_add_remote_sink 0x10440e(link, edid, len, init) (V via strings), dc_link_remove_remote_sink 0x104542, dc_sink_create 0xfc5c8, dc_sink_retain 0xfc4e0, dc_sink_release 0xfc53e, set local sink 0x10452d (`link+0x28=sink; link+0x34=(sink!=0)`) (V).

## 2. Virtual signal support exists
- Signal enum (V, stringifySignalType 0x43d60 and table at 0x278cb8): 0x20 DP, 0x40 MST, 0x80 eDP, 0x100 HDMI FRL, **0x200 VIRTUAL**, 0x400 "Virtual HDMI FRL".
- create_links 0x104b8a(dc, num_virtual_links) builds virtual links: size 0x340, connector_signal=0x200, link_id 0x3164 (CONNECTOR_ID_VIRTUAL), virtual link encoder via 0x15d7e6 (V). resource_construct 0xb3389 makes one virtual stream encoder per virtual link (virtual_stream_encoder_create 0x111aed, engine 0xc) (V). The count comes from **dc_init_data+0x54** (AmdDalServices+0x5ec). initPopulateDcInitData 0x65814 never writes it (V), so it is 0 (I).
- update_stream_signal 0x19638e: stream->signal = sink->sink_signal (or the connector signal when NONE). 0x200 passes through. 0x400/0x100 are re-mapped to TMDS 4 or 0x100, so 0x400 is no use (V).
- Clock: resource_map_clock_resources 0xb6cf8 gives signals {0x20,0x40,0x80,0x200} pool->dp_clock_source (pool+0x380). Other signals get a PLL (V).
- core_link_enable_stream 0x172587 returns at once for 0x200/0x400 unless dce_environment (ctx+0x20) is 1 or 2 (FPGA/DIAG). So no PHY, link training or transmitter commands run (V).
- link_enc validate_output_with_stream-like 0x135dcc returns true for 0x200 (V code, I name).
- **Caveat (V):** the dcn3 clk_src funcs table at 0x2a61d8 = {0xc7e18, **0xc90a1** program_pix_clk, 0xc9246 dcn3_get_pix_clk_dividers, 0xc8893}. 0xc90a1 writes the DP DTO PHASE/MODULO registers directly only for DP/MST/eDP/FRL. VIRTUAL falls through to dce112_program_pix_clk 0xc8c45, which calls bios->set_pixel_clock (set_pixel_clock_v7 0x139468). That runs ATOM table 0xc via cgs, or the DMUB path when ctx+0x88 dmub_srv and dc+0x259 are set.

## 3. Built-in override and fake mechanisms
- **AmdDalServices::linkToDiagMode 0x6ada0** (V): a built-in "fake sink". It works for DP/MST/eDP connectors only: dc_sink_create{0x20, link}, then dc_create_stream_for_sink 0x196576 with a hardcoded 800x600@60 stream, then dc_commit_streams 0x10035b. It is the pattern to copy, but it cannot be used on HDMI.
- The FB 'edid' attribute (setAttributeForConnection 0x35c80, from AGDC setFbEdid 0x3d928) stores fb+0x1f8/0x1fc. Only getDDCBlock 0x548c and getAppleSense 0x5764 read it. It changes the EDID the OS sees, not the DAL sink (V).
- Registry keys DalForceEnumEDP, DalSkipDetectionLT, DalDisableLTTPR (0x65814/0x661f2) exist. I found no virtual or headless key.

## 4. Recommended hooks
**A (preferred): repurpose the existing HDMI dc_link.**
1. Wrap dc_link_detect 0x16f799 (prologue `55 48 89 e5 41 57 41 56 41 55 41 54`, `bool(dc_link*, int reason)`). For the target link (link+0x30 index, or link_id +0x1bc):
   - init = {u32 sink_signal=0x200 @0; dc_link* @8; u32 dongle_max_pix_clk @0x10; u8 converter_disable_audio @0x14}
   - sink = dc_sink_create(&init)
   - memcpy(sink+8, edid, len); *(u32*)(sink+4) = len (max 0x800)
   - dm_helpers_parse_edid_caps(link, sink+4, sink+0x808)
   - release the old local_sink, call 0x10452d(link, sink), return true
2. Wrap program_pix_clk 0xc90a1(clk_src, pix_clk_params, pll_settings). When params+0x10 == 0x200, set it to 0x20 for the call so it takes the register-only DTO path, then restore it. Without this, VIRTUAL runs the VBIOS SetPixelClock.

**B: virtual link.** Set init_data+0x54=1 in wrapDcCreate. This is the clean Linux path (virtual link encoder and stream encoder). But Apple has no AmdLink for the extra index (the ATOM table drives createLinks), so a connector entry would also have to be faked. Higher risk.

Struct offsets (V): dc+0x308 ctx, +0x378 link_count(u8), +0x380 links[], +0x3e0 current_state, +0x3e8 res_pool. link: +0x28 local_sink, +0x30 index, +0x34 type, +0x38 connector_signal, +0x140 dc, +0x148 ctx, +0x158 link_enc, +0x1bc link_id. sink: 0x990 bytes, +0x978 link, +0x98c refcount. stream: +0 sink, +8 link, +0x3ec signal. pipe_ctx at state+0x1e8, stride 0x530, +0x2e0 clock_source.

**Risks:**
- Apple-side consumers of signal 0x200 are unverified: AmdLink/translateLinkDescriptor, HDCP convertConnectionType, AGDC, and our own wrapReportLinkInfo, which keys on 0x100/0x400.
- The 0x16f799 wrapper skips its idle enter/exit calls 0x184b24/0x184bfa.
- Re-entrancy with the 0x74ada EDID bridge hook.
- core_link_disable_stream skipping virtual is not verified.
- The DTO register indices need the DCN 3.0.2 to 3.1.5 translation.
- With no PHY, nothing reaches a real panel. Only OTG/CRC/capture can confirm scanout.
