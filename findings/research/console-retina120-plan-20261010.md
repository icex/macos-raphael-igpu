# Native QEMU Retina and120Hz experiment

Candidate430 isolates3840×2160 backing pixels /1920×1080 logical at120Hz.
The external HDMI result establishes GPU/display capability; it does not measure
the virtual capture and SPICE pipeline. No physical HDMI changes are required.

Hypothesis: the installed presenter already supports120Hz, but the external
holder, launcher and reviewed host contract force60. Add a persistent60|120
preference, keep legacy60 by default, match static/dynamic mode refresh, verify
CoreGraphics readback, request matching ScreenCaptureKit interval, and bind the
exact SPICE rate through manifest, plan, admission and live identity.

Falsification: a selected120Hz preference with a non120 CoreGraphics mode, wrong
presenter argument, or wrong observed SPICE rate rejects configuration success.
Source sample cadence, snapshot commits and observed client frame identities
must be measured separately; mere mode enumeration is insufficient. QEMU's
integer refresh timer is a ceiling rather than exact120Hz scheduling.

The first test retains32MiB snapshot buffers and existing signed presenter so
resolution-capacity and TCC changes do not confound refresh qualification.
Full5K5120×2880 BGRA requires58,982,400bytes, exceeding32MiB. A later coherent
64MiB profile must change QEMU staging/pool, driver private buffers, presenter
mapping validation and all geometry bounds together, preserving legacy32MiB
compatibility and refusing5K fallback onto the legacy path.

At2× guest UI scale, stock SPICE monitor requests already include host GDK scale.
Do not blindly double GDK2 dimensions. Qualify fixed standard Retina modes first,
then explicit host-scale-aware automatic sizing and pointer coordinates.
