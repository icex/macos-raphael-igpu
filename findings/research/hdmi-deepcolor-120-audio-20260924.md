# Native1080p packing fix and required follow-up — 2026-09-24

Candidate322, sourcebd981b1, run0cb060da92bd7d7a2afdb4dd7002f54b,
MODE2#250, build1bb07bc24ec845be8f7fbd605a9ddb56.

## Mechanism and physical result

The default-off `rgpuhdmideep=1` copies HDMI deep-color packing into PHYPLLA
pixel resync ratio bits4:5, preserving other bits and requiring enabled PHY
clock and readback. Linux dce112_program_pixel_clk_resync uses the same ratio.
Native DMUB payload remains unchanged. After fix PHY0x113 matches10-bit HDMI;
previous0x103 used8-bit division and gave interleaving.

User confirms correct native1920x1080@60 picture. After switching to native
1920x1080@120 user says "I think120hz works too". CoreGraphics current-mode
readback is120Hz; HDMI_CONTROL0x1101001f, PHY0x113, HUBP0_CNTLf0102,
DET0=303, COMPBUF13, FLIP_PENDING0, DPG07800438 and scanning OTG.
No captured fetch timeout or underflow. This does not measure delivered FPS
or color accuracy. Candidate321 had already delivered an almost-perfect
1920logical/3840pixel HiDPI60 picture.

## Remaining requirements

User explicitly requires1920x1080 HiDPI at120Hz and actual HDMI audio.
Samsung OdysseyG95NC EDID advertises VIC1184K120, maxTMDS600MHz,
FRL12Gbps x4. CoreGraphics lists4K30/60 only, although native1080p120 exists.
Linux DCN315 resource supports FRL; investigate Apple's link capability and
FRL selection path rather than assume hardware lacks support or overclock TMDS.
AGDCDiagnose records active HDMI; its0Mbps/lane DP fields do not measure TMDS.

HDMI audio7b:00.1 (1002:1640) remains snd_hda_intel, not assigned to QEMU.
USB/BlackHole sound is a separate transport. Next candidate needs exact two
function passthrough, AppleGFXHDA config ID/pairing, and audio teardown checks.
The historical audio plan's remote-only priority and no-DMCUB-start text are
superseded by current user requests and314 firmware evidence.

## Capture and cleanup

1020 host tests OK (3 skipped), finalCORE_PROBE_PASS, complete capture.
Guest exited-after-guest-request; recovery status recovered, authorizes_launch=true.
[Artifact hashes](hdmi-deepcolor-evidence-20260924.json).
