# Depth/stencil and color resolve qualification — 2026-09-16

Run `ca1fd405218e175788a332ff0691a058`, candidate280/metal-127/depthstencil,
MODE2#164, twenty-third exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. Driver/QEMU unchanged.
[Artifact hashes and summary](depth-stencil-evidence-20260916.json).

128 cases pass:32 rounds each for64×64 and1003×769, at1× and4× samples.
All49,625,792 RGBA8 pixels match the CPU oracle with zero mismatches.
Depth/stencil format is Depth32Float_Stencil8, private textures. Four ordered draws:

1. Full red at depth0.6, less comparison, depth write, replace stencil with1.
2. Left scissor green at depth0.2, same state, replace stencil with2.
3. Full far blue at depth0.8, less comparison, stencil keep; must be rejected.
4. Full near magenta/cyan at depth0.05, stencil equal2; only left region changes.

Final left color alternates each round, right remains red. Fragment shader exports
explicit depth (`depth(any)`). The4× cases resolve color to a single-sample texture;
managed-buffer readback is GPU-synchronized and strips aligned row padding before
CPU comparison. Both command buffers complete per case, with20s waits and180s
process watchdog. No live validation layer was enabled.

Supplied MTL source: GFX10_MtlRenderCmdEncoder setDepthStencilState at
7ffb08d697d1 updates depth/stencil state, calls UpdatePrimBatchBinning and emits
hardware commands; setStencilReferenceValue at7ffb08d69d6e maintains front/back
reference values separately from that state. These made state transitions an
explicit target beyond earlier color-only probes. Existing global no-binning guard
remains unchanged; no patch was inferred from decompiled field types.

Independent results: baseline CORE_PROBE_PASS, valid capture375 records/snapshot10,
no capture loss. Guest-request shutdown; schema6 recovered/authorizes_launch=true,
CP_STAT=0, active_after=0, no forced queue clears/timeouts, recovery kernel_messages=[].
PerfPowerServices PID152 remains0.0% CPU,0.69s cumulative.

Scope: bounded color-oracle validation of late-depth/stencil transitions and color
MSAA resolve. Not depth/stencil resolve, depth-texture sampling, retained attachments
across separate render passes, every depth format, interprocess events, independent
host boots or full Metal conformance. Compilation succeeds with one SDK deprecation
warning for sampleCount (equivalent older spelling of rasterSampleCount); shader and
GPU execution both pass. No performance conclusion from this short workload.
