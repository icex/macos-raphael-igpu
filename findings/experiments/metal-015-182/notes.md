# metal-015 candidate 182

Run ID: `113c5b949683bf38fd5a807447088a69`
Boot ID: `d67da91d-94e6-42f0-8dd1-78b42f5496e1`
Manifest SHA256: `9efb977fa6046e8fe837e59d3c744c68915b2d96ccfcd72f4e23061cdc975f55`
Build ID: `9f8584cf8a0246308772d6958443e503`
Operator log SHA256: `993af4a336f82387b9e59b2e052db71bfe4c8546a0d20341f2479cc4e9aa3a79`

The bounded ordinary run reached the native entry gate and reported `VM: entry-gate init marked=1 aperture=1 mode=3`. The final verdict is `INVALID`; no valid Metal probe result was produced. The earliest recorded failure is `vmid2_entry_conversion_no_pde`, with fault status `0x2009bb` at address `0x400200000`; entry conversion reported no child PDE crossing the aperture and critical capture was lost.

The coordinator's recovery receipt reports schema 6, status `recovered`, and `authorizes_launch=true`, with reset methods empty, BAR5 accessible, GC quiesced (`active_before=2`, dequeued=2, timeouts=0, forced_inactive=0), and the graphics-pipe guard reservation unchanged. Together with graphics retirement, authenticated lifetime readbacks and final inactive checks, this demonstrates cleanup for this forced closure. It does not change the invalid functional verdict, establish universal crash recovery, or bypass subsequent launch-admission requirements.

The final host snapshot records boot `d67da91d-94e6-42f0-8dd1-78b42f5496e1`, driver `vfio-pci`, group 31, `active_vm=false`, `watchdogs_verified=true`, `capture_ready=true`, and `sleep_inhibited=true`. These are observed snapshot facts only.

Recovery replay has tolerance `terminal-prefix-open`, snapshot count 205, and 69 corrupt lines. The raw verdict, serial, recovery receipt, recovery replay, host snapshots, shutdown, supervision, and event files are preserved under `raw/` with `raw-sha256.txt`.

This is the fourth consecutive hardware cycle with the same unresolved SDMA/entry-conversion boundary. Mandatory Astra review must occur before any further hardware cycle. No retry, recovery action, reset, MMIO, sudo, or additional launch was performed here.
