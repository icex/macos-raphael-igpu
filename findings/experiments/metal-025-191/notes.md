# Candidate 191 / metal-025 evidence note

The immutable source of truth is
`/home/bogdan/macos-vm/run/metal-025-191`, run ID
`20187457d3e5ad837617f89efa477219`. This note does not copy the large logs.

The strict native Metal probe enumerated `AMD Radeon Navi23`, reported Metal 3,
compiled shaders, entered compute and committed its command buffer. Completion
timed out after five seconds with zero completed command buffers and zero compute
rounds. The checked verdict is valid `EXECUTION_FAILED` at `first_submission`.

The collector change passed its real-load purpose: `critical.txt` contains
560,666 bytes, and recovery replay accepted snapshot 7 with 300 records, zero
corrupt lines, no incomplete snapshot and no open attempt. This is distinct
capture progress; the unchanged GPU execution failure remains unresolved.

Cleanup is the admission blocker. Recovery schema 6 is `incomplete` and
`authorizes_launch=false` because host KIQ did not consume graphics
`UNMAP_QUEUES` and its write pointer did not clear. Host-after shows no active
VM, the device still on `vfio-pci` and accessible, sleep inhibition active and
watchdogs verified. The same-boot ledger is now three of three. No retry, reset,
rebind, debugger attach or budget extension is authorized.

Key SHA-256 identities:

- manifest: `8271c546213e449d73c0ef4ae2e6b8fb5b6ebb22fdbe6d6f4a5f88e25127c1d9`
- verdict: `b8c3f6ba481f07104f523eab74f68c9c707d72e578f0551ab55772a252a66d63`
- probe: `c69369703d7b26f1495ff1e3ffafa7d16d507d6c4413288d6b4aa31438e3a665`
- serial: `5c791de22e64dbe0d8e013a9baa2dd247ba45d64c87dc9614bd2b0b2e26e562d`
- critical: `d3ac2d3ba32dc9308943846b58d73ef3f36935bbc4d37c891cc7d8093670bd71`
- recovery replay: `063fa53cdabd29dbaee58bf535048076900b294bead79d93b57e951ac093d004`
- recovery: `0d5420be9c85a5bc22ef43f166ec14203ddb70448c4e059866227add594b864e`
- host-after: `baaaa152974422b2a42d3efbe839ef154778ca2456ae9e043edd0ee0210366b0`

The first identity record was rejected before staging writes because it used
noncanonical keys. The first manifest later exposed the old live collector and
remains preserved as superseded at SHA-256
`ffdbcf8304937a6d56c21462e75b0a5c0e0f4fef5c8dc2a6aafb59dfaab60547`.
The launched manifest pins the reviewed live collector SHA-256
`3dd229f4ea4df1c0d3a9f3c5f50becd69b2664bf85ebe8c515893488ceaa4ad8`.

`GDB=on` remained available, but the failed probe left no safe authenticated
post-probe debugger interval before bounded shutdown and cleanup. No debugger
was attached. The archived early-rendezvous proposal remains unqualified and
cannot be used while recovery and launch admission are blocked.
