# Live status — 2026-10-09

## Candidate351: destination write cost localized; normal desktop restored

Run `60b6600fc4514bab8b734e41b70ace39`, metal-194, build1.0.351,
MODE2#289, bootba51b3c6. Native Metal/WindowServer/display checks pass.
Actual SCK source→RAM is cheap; both direct and RAM→console HiDPI writes
remain around15–17ms. Native second writes are often cheaper regardless of
order. All32 full-byte comparisons pass across O0/O2 of identical source;
compiler optimization does not eliminate the slow writes. No speedup claimed.

Normal Settings UI renews capture permission without user intervention.
Both moving fixtures finish; diagnostic flag removed, approved O2 presenter
returns to normal capture and actual virt-manager desktop. Display awake.
352's separate software KVM test establishes dirty-log rearming first-write
cost, not yet Bochs-specific causality. Next: opt-in full-refresh Bochs test,
preserving default behavior and migration tracking; quantify CPU/bandwidth.

Capture CORE_PROBE_PASS, earliest_failure=null. Shutdown:
exited-after-guest-request; real guest-shutdown terminal process_exited=true.
Both EOF hooks use already-reaped natural exit (~0.455s), so350's zombie
refusal remains unresolved and new predicate diagnostics were not exercised.
Recovery recovered, authorizes_launch=true. VM/cycle stopped, host awake.
No reboot/rebind needed.1181 host tests pass,8skip; kext/manifest match351.

Candidate changes remain local. Dev277ff81 hosted test/build green; main
unchanged. General desktop, lifecycle, automatic resize, atomic presentation
and VirtualBox qualification remain open.
[Evidence](findings/research/console-dirty-write-20261009.md) ·
[Raw samples and receipts](findings/research/console-dirty-write-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-351-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-352-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
