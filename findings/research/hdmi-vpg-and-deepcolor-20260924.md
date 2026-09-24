# HDMI infoframe memory and deep-color clocks —2026-09-24

Candidate320 fetch works after DET0 allocation. User saw HiDPI image with pink hue,
low-resolution1080p interleaving,30Hz black. VPG0_MEM_PWR0x110 means forced light
sleep and memory asleep. Linux dc/dcn31/dcn31_vpg.c vpg31_poweron clears bit4 and
sets bit0. Candidate321 applies that default-off wake before native packet access.

Run13246b9a0f02e33e0a4bb92d2e55f6d0, source2242840, build e5801d0c54ea4d2eb0508e0091c35e57:
readback0x110→1; native packet0 header0x000d0282 and first payload0x80885ef4.
AVI DB1=0x5e identifiesYCbCr444. RGB-like FMT/DIG mode0 does not distinguishRGB444
fromYCbCr444; earlier "RGB encoder/FMT" wording was insufficient to identify color
space. Missing metadata is consistent with320 pink hue;321 user confirms full
picture and "default looks almost perfect" at1080HiDPI/3840x2160pixels60Hz.

Low-resolution1080p60 remains interleaved. Capture321-native60 shows HDMI_CONTROL
0x11010019 (10-bit) but PHYPLLA_PIXCLK_RESYNC_CNTL0x103 (ratio0). Linux
clock_source/dce_clock_source.c dce112_program_pixel_clk_resync sets bits4:5 to1
for10bit (TMDS/pixel=5:4); dcn31_program_pix_clk also sends the depth toDMUB.
Apple decoded00139468 builds set_pixel_clock_v7; observed cmd has ratio0.

Candidate322 independently targets this mismatch: after native HDMI_CONTROL write
and before native unblank, mirror only enabled deep-color ratio into PHYPLLA
bits4:5, preserve other bits, reject inaccessible reads/unclocked PHY, read back.
This is opt-in; no new firmware/SMU commands. Falsifier: readback ratio1 but1080p
still interleaved. First qualify60Hz, then120Hz; restore workingHiDPI if needed.

321 finalCORE_PROBE_PASS, completecapture, exited-after-guest-request, recovered,
authorizes_launch=true. Full physical color fidelity and120Hz remain unqualified.
