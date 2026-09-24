# Physical HDMI: verified scope and setup

Updated 2026-09-24. The tested monitor is the Samsung Odyssey G95NC on the
Raphael iGPU HDMI port, with macOS Sequoia 24G830.

| Mode or feature | Observed result |
|---|---|
| 1920×1080 HiDPI, 3840×2160 backing, 60 Hz | User confirms a full picture (321). |
| Native 1920×1080, 60 Hz | User confirms correct picture after the HDMI deep-color divider fix (322). |
| Native 1920×1080, 120 Hz | Listed by macOS; user reports it appears to work. Sustained timing remains unqualified. |
| 1920×1080 HiDPI, 3840×2160 backing, 120 Hz | Still absent; ongoing mode-validation and link investigation. |
| HDMI audio | Audible through Samsung headphone/audio output, confirmed by user (323); 2 channels at 48 kHz. |
| DisplayPort, HDR, other monitors | Untested. |

The fixes include display-fetch buffer allocation, infoframe memory wake and
matching the HDMI deep-color pixel divider. These experiments require the exact
24G830 driver, matching Lilu, VBIOS graft and the complete candidate configuration;
the kext alone is insufficient. Use [metal-171](../experiments/metal-171.json)
and the [supervised cycle](running-an-experiment.md), not a partial list of flags.

HDMI audio uses the separately checked Raphael function `0000:7b:00.1` in its
own IOMMU group. The tested guest places graphics/audio at `00:06.0`/`00:06.1`,
spoofs the audio device as `1002:ab28`, and enables the guarded same-slot
AppleGFXHDA pairing hook (`rgpuhdmiaudio=1`). `HDMI_AUDIO=on` explicitly opts into
that passthrough topology. Generic QEMU examples do not enable it automatically.
The host helper checks identity, ownership, power and audio DMA quiescence; keep
all checks and teardown receipts. Never bind either function back to a host
driver within the same boot.

Select Odyssey G95NC as macOS sound output and listen through the monitor's audio
output. Verify display-awake assertions before every physical test. Candidate323
completed its core probe, capture, guest-request shutdown and authorizing GPU
recovery; audio teardown reported DMA disabled and no errors. This does not
qualify arbitrary guest crashes, repeated host boots or long-duration playback.

[Audio evidence](../findings/research/hdmi-audio-candidate323-20260924.md) ·
[Live status](../status.md) · [Roadmap](ROADMAP.md).
