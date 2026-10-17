#4K120 timing limit — candidates324/325

324 read-only trace: Apple receives3840x2160 clock1188000000Hz four times.
validateTimingRange rejects it against max625000000Hz with divider1; outer
validateDetailedTiming returns0xe00002c7. HDMI capability translation retains
FRL flags: raw0x3df→0x7df. This rejects missing EDID timing or missing encoder
FRL capability as the immediate blocker.

24G830 Navi2::getCapability0x3aeaa selector13 chooses BIOS boot display clock
when PowerPlay reports unsupported. This project deliberately disables that
unsupported power backend. Generic AsicInfo::getCapability0x3bde2 selector13
instead reads the native DAL capabilities+0x220. Navi2::getTimingRange0x3af60
uses this result times1000 as the timing range limit. Correct units are kHz in
the getter and Hz in the timing structure.

325 uses the generic getter only for selector13 and only substitutes when
original is the observed625000kHz, native is higher and at most2400000kHz.
No literal requested hardware clock, validation success, or FRL support is
fabricated. Clock programming and downstream link/bandwidth checks remain
native. Both entry sequences verified against24G830; base getter called
without rewriting its instructions. All other selectors preserve original.

324's160 timing records plus range/capability logs overflowed CR2. It is INVALID,
not a capture-qualified run; raw serial supports the narrow mode-rejection
finding. Clean guest shutdown and audio DMA off, then supportedMODE2/noqueue
recovery authorized same-boot reuse.325 logs only4 high-clock timing outcomes,
4 range outcomes,4 descriptor translations and2 clock-capability observations.

[324 artifact hashes](hdmi-timing-rejection-20260924.json).
