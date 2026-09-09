# Candidate 175 retained KIQ doorbell-zero and gate closure

This archive preserves the two root-cleared one-shot transactions for boot
`5d6f45d0-4384-4340-b819-7751bc26ebb3` and run
`1a065e4f5f674cc0a26d4e9dbdf59649`. Both transactions are permanently
nonauthorizing. They do not amend the incomplete schema-5 recovery receipt and
do not authorize a VM launch, recovery, or additional cleanup.

The first transaction used the exact retained stopped state recorded by
preparation result
`99bb203ee46b24c1adf55c38366dadbaa238776508cf9d1d46842e125ebbd8ea`.
Its full two-pass pre-scan found all 64 HQDs inactive, selector 9 at
`ACTIVE=0`, `DEQUEUE=0`, `RPTR=0`, `WPTR_LO=0x100`, `WPTR_HI=0`, all compute
doorbell enable bits clear, both MECs halted, CP idle, polling/ranges off, and
SDMA halted/idle with PAGE inputs disabled. It enabled only selector 9's
doorbell-zero control and the global PQ doorbell gate, issued one native aligned
64-bit BAR2 doorbell-zero store, and observed `ACTIVE=0`, halted MECs, and
`WPTR_LO/WPTR_HI=0/0` after the cross-BAR posting read. The measured interval
from before the first enable store through the global-close attempt was 41,600
ns.

That transaction is deliberately recorded as failed. The doorbell set
`CP_PQ_STATUS.DOORBELL_UPDATED`, changing the global status from the written
`0x2` to `0x3`. The first tool's conservative close-preimage rule rejected
`0x3` before issuing its global-close store. It did disable selector 9's
per-HQD doorbell (`0xc0000000` to the HIT-only readback `0x80000000`) and restore
selector zero. Its two stable final passes showed selector 9 inactive with all
pointers zero, but the global PQ status remained `0x3`. No retry occurred.

The separate closure transaction pinned that exact failed result and exact
full final scan. It performed one native aligned DWORD read-modify-write of
`CP_PQ_STATUS`, reading `0x3`, writing `0x1`, and reading back `0x1`. Bit 1
(`DOORBELL_ENABLE`) is clear; bit 0 (`DOORBELL_UPDATED`) remains as status. Its
two stable post-passes differ from the pinned pre-state only in
`CP_PQ_STATUS=0x1`. Selector 9 remains `ACTIVE=0`, `DEQUEUE=0`, `RPTR=0`, and
`WPTR_LO/WPTR_HI=0/0`, with per-HQD doorbell `0x80000000`. CP remains idle,
ME/MEC and SDMA remain halted, SDMA remains idle, PAGE inputs remain disabled,
polling and doorbell ranges remain zero, and selector-zero restoration
completed.

Both postflights retained PCI command `3`, power state `D0`, power control
`on`, runtime status `active`, VFIO enable count `0`, no active VM, the active
host inhibitor, and no new journal fault. The used-boot ledger stayed at SHA-256
`69b8e1464a6866d3da2518e5db7222b0d557e0eb7f3ac3c27ebffbec139b9d15`.
The old incomplete receipt stayed at
`9cf80653e198faa09c6f4da456e8495e07a045015c6ac0b64a7561ffbfc85fc7`,
and the original candidate-175 recovery artifact stayed at
`117d2d4cea6b007c49fc797af7c64ef78bfeb4da8acebaa245abd945372e3e4d`.

Frozen source provenance:

- doorbell-zero tool: `eb9257a9ed0d9453e171a4be86466d690f40b525444ce99d5ae248aaa30f4d30`
- global-close tool: `1e44e1342a0104c72694103d8749cfec4d28e2ecc294f52f6f2be2b12cc72428`
- retained preparation: `45535eeaff653ca60ae880cc32530016886a94985a3d30b6bff51d10cefb7085`
- retained idle scanner: `0c4f4bc9bd87aa41630349616dbc545d3114018ee93f80ab9c0a82da5f649e79`
- retained scratch observer: `cf6513926a9c9fbf5f11df3cd1980ca3de90a786d8ef4c5f21d8764d5755b3d9`
- VFIO recovery helper: `d4e4994885ad8300b89f96ae78a7098e872b64055cc8123146959d2a66c39e21`
- loaded `_ctypes` binary: `16ff8ef1cf8e38262db2fbcf1b953e44debacacc62c313f1d52b6ceaa8b48592`, build ID `033feee458ae59a5c8aebcae73512fde5dc0f163`
- doorbell-zero tests: `d3d68e49e0906da9720aca64f762d80e53c8c482daf5e45764819315c4c45f42`
- global-close tests: `e2542781051958104627a058b046afc3df349eb369924962b18dbd606f886908`

`offline-tests.log` records 21/21 focused tests. `SHA256SUMS` covers every
copied immutable artifact, both preflight proofs, the test log, and these notes.
