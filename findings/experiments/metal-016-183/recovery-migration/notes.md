# Candidate 183 recovery migration

The single authorized recovery-only attempt was executed after the metal-016-183 run. The pinned wrapper and proof hashes matched. The reconstruction itself passed its integrity checks, but the receipt did not authorize a launch because host KIQ retirement was blocked by active HQDs.

The receipt records `gc_quiesce.status=quiesced`, both PSP destroy commands confirmed, and no kernel messages. This must be read together with the retirement result: `host_kiq.status=blocked-active-hqd`, 9 active HQDs, 1 dequeued, 8 dequeue timeouts/forced inactive, `gfx_retirement_confirmed=false`, and `gfx_ring_clean=false`. Quiescence and graphics retirement are therefore preserved as separate facts; quiescence did not establish a clean graphics retirement.

The replay reconstruction passed; the 27 corrupt transport lines belong to the captured serial transport and are not the cause of the incomplete recovery. The canonical receipt is `status=incomplete` with `authorizes_launch=false`. No further launch, retry, reset, MMIO, or alternate recovery was performed.

Original metal-016-183 serial, verdict, and recovery evidence remain unchanged in the parent run directory. The post-run host snapshot remained awake with no active QEMU/container.
