# Candidate 175 retained KIQ preparation

This archive preserves byte-identical copies of the one root-cleared preparation transaction for boot `5d6f45d0-4384-4340-b819-7751bc26ebb3` and run `1a065e4f5f674cc0a26d4e9dbdf59649`. The input was retained-idle result `589278713643fc52db7f5a0a8ef7f4f5bab0a8e38aec5a209fa27b8ff9ffe42d`.

The exact stopped-state preconditions passed. The first native DWORD store changed SDMA PAGE IB control from `0x101` to `0x100`, and its same-register posting read returned `0x100`. The second changed PAGE RB control from `0x80840021` to `0x80840020`, and its posting read returned `0x80840020`. Both PAGE enable bits therefore cleared successfully in the Apple 5.2 IB-then-RB order.

Before the third store, selector 9 still had `ACTIVE=0`, `DEQUEUE=0`, `RPTR=0`, `WPTR_LO=0x100`, `WPTR_HI=0`, and doorbell control `0x80000000`; CP/PQ/range, MEC-halt, and SDMA-halt/idle gates all passed. The native `WPTR_LO=0` store was attempted, but its posting read returned `0x100`. The transaction failed at this boundary and was not retried.

Selector zero restoration completed. Two full post-passes were stable: the two PAGE enable bits remained clear, selector-9 WPTR remained `0x100`, all 64 HQDs remained inactive, the same eight doorbells retained `0x80000000`, both graphics pipes remained inactive with zero doorbell status and WPTR, and every other captured value was unchanged. Host, journal, ledger, and the old incomplete recovery receipt were unchanged.

The result is `failed` and every authorization field is false. The partial PAGE success does not authorize another launch, recovery, cleanup, or another attempt. The frozen transaction source was `45535eeaff653ca60ae880cc32530016886a94985a3d30b6bff51d10cefb7085`; the scanner was `0c4f4bc9bd87aa41630349616dbc545d3114018ee93f80ab9c0a82da5f649e79`; the retained observer was `cf6513926a9c9fbf5f11df3cd1980ca3de90a786d8ef4c5f21d8764d5755b3d9`; and the recovery helper was `d4e4994885ad8300b89f96ae78a7098e872b64055cc8123146959d2a66c39e21`. `offline-tests.log` records 11/11 focused fake-transport tests.
