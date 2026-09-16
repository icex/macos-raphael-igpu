# Main10 decode qualification and encoder limitation — 2026-09-16

Candidate280, unchanged driver/QEMU, metal-127/attempt main10. Run
`f846abef4a573a0059fbe0ecdd28ecfc`, MODE2#163, twenty-second exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`.
[Raw artifact hashes and summaries](main10-qualification-evidence-20260916.json).

## Observed function

Explicit VCP software HEVC encoding produces Main10 4:2:0 hvcC (profile2, luma/chroma
bit depths10). Decode the same compressed samples first with VCP/hardware disabled,
then with automatic required-hardware decode. The hardware property is true.

| Resolution | Frames | Luma values | Chroma values | Maximum hardware/reference difference |
|---|---:|---:|---:|---:|
| 1280×720 | 16 | 14,745,600 | 7,372,800 | 0 |
| 1920×1080 | 16 | 33,177,600 | 16,588,800 | 0 |

All32 frames uniquely identified by PTS. All71,884,800 luma/chroma samples match
software exactly, including boundaries. The acceptance tolerance was two10-bit
codes; actual maximum was zero. Reference buffers contain many non-multiple-of-four
values, so this is not merely eight-bit data stored in16-bit containers. The separate
lossy synthetic-pattern check excludes narrow boundaries; its maximum was1/2 codes
respectively against a declared48-code tolerance. That looser gate is not the
hardware-vs-reference fidelity claim. Reference copies use packed rows independent
of the hardware/software buffer strides. Maximum retained reference memory is about
95MiB at16×1080p. The process has a180s watchdog.

The hardware HEVC encoder session creates/prepares and reports hardware=true,
but setting HEVC_Main10_AutoLevel returns -12900 before any frames are submitted.
A separate no-frame capability probe confirms its ProfileLevel SupportedValueList
contains only HEVC_Main_AutoLevel for both420v andx420 input. Main setter returns0;
Main10 setter returns-12900. EncoderID is com.apple.videotoolbox.videoencoder.hevc.gva.
This does not invalidate prior Main8 encoding. Do not advertise Main10 hardware encode.

## Supplied-source basis

In `re/decompiled-24G830/VideoToolbox-full/functions`, function7ff812ce2aac maps
HEVC_Main10_AutoLevel to supported-profile ID2. Main10 is not an unknown API string.
AppleGVA function7ffa067060b6 checks HEVC bit-depth/output compatibility and rejects
non-eight-bit content in a420v output surface. The probe therefore validates hvcC
and requests/verifies x420 output instead of accepting a session-create result alone.

The VCP software encoder/decoder return -12900 for their hardware-status property.
Two initial observer attempts stopped at those checks (first before encoding, second
before reference decode). Those outputs are retained under initial-* and encoder-bound-*;
they are not hardware decoding failures. The revised probe binds software EncoderID /
DecoderID to VCP, explicitly disables hardware for reference creation, and additionally
queries the encoder identity. Hardware decoding still requires a valid true hardware
property. No driver/API capability advertisement was changed to make the test pass.

## Independent qualification outcomes

- Function: the two Main10 decode cases pass; Main10 hardware encode is unsupported
  by this session's advertised profile set and rejected before execution.
- Identity/capture: baseline desktop probe passes, strict capture valid,398 critical
  records (snapshot18), zero reported capture loss.
- Cleanup: exited-after-guest-request; schema6 recovered/authorizes_launch=true;
  CP_STAT=0, active_after=0, no forced clears/timeouts, recovery kernel_messages=[].
- Overall baseline: CORE_PROBE_PASS. This does not promote the failed encoder case.

Raw desktop RFB capture after codecs appears clean (wallpaper/menu/Dock, no native
material window present). PerfPowerServices PID152 remains0.0% CPU,0.75s cumulative.
Limits: short synthetic clips, one guest boot for these Main10 cases, two sizes,
4:2:0 only. Arbitrary media/HDR metadata, long-duration/Main10 concurrency,
Main10 encoding, independent host boots and physical scanout remain unqualified.
