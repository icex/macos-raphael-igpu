# metal-016 / candidate 1.0.183

Run ID: `f1728b74e128c5acd35661334bff12be`
Boot ID: `d67da91d-94e6-42f0-8dd1-78b42f5496e1`
CID: `1aae2d1f19774cfd9e8d852dac67a6a350a9eafd00280f79ce716daa1f0943ea`
Manifest SHA256: `e809cee6b8dc3cb8749d56dcedeb4dcdb55ab98caf21ee3a5bdd7de59f660775`
Build ID: `1d5f98d2e5b641eeab1869987f569e73`

## Observed run

The bounded run reached the guest and native mode-4 startup. The serial stream records `VM: entry-gate init marked=1 aperture=1 mode=4`, the real entry-update route, and returned source conversion samples. The first update summary recorded 206 converted entries; a later summary recorded 347. A representative child sample converted source `0xf40b6f4000` to `0x84b6f4000` and constructed the corresponding entry. Submission totals progressed to `113/113/0`.

The worker emitted dispatch-phase walk records. These are raw worker walk observations only; they do not establish a prepared-phase BAR walk. The recorded walks show complete entries for `0x400100000` and `0x4000c0000`, while walks for `0x400200000` and `0x400180040` were incomplete.

The serial includes pre-clear faults with status `0x101b3a` at `0x400900000` and `0x1009ba` at `0x401180000`, followed by SDMA page occupancy/stamp timeout evidence. No valid Metal probe result was produced; full Metal acceleration remains unverified.

## Verdict and lifecycle

The final verdict is `INCONCLUSIVE`, earliest failure `identity_or_route_missing`, with `capture_loss` evidence. The CR2 replay had a missing chunk, so no admissible final CR2 result was available. Recovery failed with `CriticalReplayError: CR2 snapshot has a missing chunk`; there is no recovery receipt and no reuse authorization. The boot ledger contains two of three launches, but reuse is blocked by the failed recovery and no retry was attempted.

Shutdown was forced after a shutdown request; ACPI powerdown was not sent because no bounded grace remained. Host-after facts recorded vfio-pci, group31, watchdogs/capture ready, reset methods empty, device accessible, no active VM, and sleep inhibition. These are snapshots only and do not establish successful cleanup.

## Timing and preserved evidence

Supervision started at `2026-09-10T09:06:25.104Z`. The first timestamped guest `launchd` record is `2026-09-10 09:06:43.296470`, approximately 18.2 seconds later. This is a guest startup anchor, not a measurement of the OpenCore picker timeout; no picker timing was inferred.

Raw run files are preserved byte-for-byte under `raw/`; `raw-sha256.txt` inventories them. The live serial SHA256 was `af132e635729bee36634c4bd4f5280bf63735183f88b465e8a3d34c1c0df0ce1` on two consecutive reads before archival, and the archived copy has the same hash.
