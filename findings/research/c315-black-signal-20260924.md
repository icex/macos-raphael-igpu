# Candidate315-watch: signal but black

Run3d5f576073db234cc14c2191991bf3ed, same source9886c30 as315-hdmi.
User confirms physical signal with black output, unaffected by wake/input and
manual VNC resolution changes.120Hz is advertised for native1920x1080; software
mode transactions have not established a120Hz physical output.

Live read-only QEMU monitor captures (existing guest MMIO mapping; no VFIO open):
`~/macos-vm/run/c315-watch-scanout.json` and `.txt`. Current mode4K60,
logical1920x1080. DPG0_CONTROL41, identical paired colors, dimensions3840x2160.
HUBP0 clocks on, surface address programmed, SURFACE_INUSE zero and timeout2,
underflow3/7 across reads. OTG0 advances, DIG0 HDMI enabled. All delivered VBIOS
commands still consumed. Later display-idle disabled DIG and gated HUBP; disabled
guest display sleep and sent input, and active state returned.

Linux `dc/hwss/dcn20/dcn20_hwseq.c:dcn20_blank_pixel_data` uses OPP DPG constant
color for blanking. `dc/opp/dcn20/dcn20_opp.c` uses mode4 horizontal bars with both
colors equal for solid color. Apple decoded function0018f7b0 and0019021d in
`re/roadmap-24G830/AMDRadeonX6000Framebuffer-full` match generator and blank-status
access. Native blank-status code reads control/status, not color registers.

316 diagnostic replaces only OPP0 paired-color writes withff00ff00 through the
existing translated DAL accessor, bootarg rgpudcncolor=1. This preserves native
DPG enable/mode/status handshakes, avoiding a forced-mode change that could break
blank waits. It should produce a bright constant test color if this blank path
reaches HDMI. A visible test color would qualify downstream signaling only, not
framebuffer fetch or desktop. Defaults and firmware/reset behavior unchanged.
