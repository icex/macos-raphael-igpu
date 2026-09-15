# Live status — 2026-09-15

259 software firmware+committing SRAM: exact pause ACK timeout remains, desktop
passes. Forced shutdown/recovery recovered. Decoder-first attempt rejected both
H264 and HEVC hardware decoders before VCN initialization: pinned=-12906,
automatic=-12913. Software control passes3frames/maxerror1. No inference that
hardware decode exercised or that startup ordering was falsified.

260 reads the DPG SRAM LMA port after submit and pause failure. Tests whether
register image is actually present/readable rather than inferring from submit0.
No SRAM data writes, read-control address selection only (observer side effects
not excluded). Same software firmware/initialization behavior as259.

## One-run allowance
One launch candidate1.0.260 / metal-106 on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2 under current user request for continued work
and testing toward a solution. Fresh MODE2, cycle.py/manual-reuse/ack-risk,
max6000seconds, all host/identity/capture/cleanup aborts intact. Stop after
hardware H264 output or first stall and SRAM observations. No merge/push.
