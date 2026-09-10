# GUI run recovery migration

The single authorized cleanup-only runner completed against GUI run `4661e574bbd5695d00176d85bfa87325` on boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8`, using the reviewed proof and runner hashes.

The canonical receipt reports `status=recovered` and `authorizes_launch=true`. Graphics retirement was confirmed clean: 2 active queues dequeued, zero dequeue timeouts, zero forced-inactive clears, and `gfx_retirement_confirmed=true` / `gfx_ring_clean=true`. Both PSP ring-destroy commands were confirmed and kernel messages were empty. This cleanup receipt does not authorize a new launch by itself.

The proof derived serial SHA is `d33deff7cd420013a290d195967c0e43689c3810422b9647b8336a83180f0675`; the original serial SHA is `a8c7aeda24244094d2a153df066d3857f3adfa823bb4ff62bbe72a79180c765b`. Original run evidence remains in the parent run directory.
