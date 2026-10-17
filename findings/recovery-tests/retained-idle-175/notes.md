# Candidate 175 retained-idle selector observation

This archive preserves byte-identical copies of the one root-cleared selector-only observation for boot `5d6f45d0-4384-4340-b819-7751bc26ebb3` and run `1a065e4f5f674cc0a26d4e9dbdf59649`. The prior incomplete schema-5 recovery remains recovery `e503b2ca63db4e11a21494d1841dca24`; this observation does not alter or complete it.

The scanner completed two identical passes over all 64 compute HQDs and both graphics selectors. All 64 `ACTIVE` values were zero and no captured register returned all ones. Both graphics pipes had zero active, doorbell-status, and WPTR values. `CP_STAT` and `CPC_BUSY` were zero; ME and MEC halt values were `0x15000000` and `0x50000000`; PQ poll/status and global doorbell ranges were zero.

The observation failed three conservative gates. Eight ME2 queues, at selectors `9`, `521`, `1033`, `1545`, `11`, `523`, `1035`, and `1547`, each retained `CP_HQD_PQ_DOORBELL_CONTROL=0x80000000`. Selector 9 had `ACTIVE=0`, `DEQUEUE=0`, `RPTR=0`, `WPTR_LO=0x100`, and `WPTR_HI=0`. SDMA PAGE RB/IB controls were `0x80840021` and `0x101`, so both enable bits were set. SDMA auto-context-switch, GFX RB/IB, and RLC0/RLC1 RB/IB enable gates were clear; `F32_CNTL=1` was halted and `STATUS=0x46dee557` had IDLE set.

All 137 selector writes completed in the expected order and the final selector-zero write completed. Userspace mapped BAR5 only; it performed no engine, PSP, HDP, queue, doorbell, reset, or launch mutation. The postflight host state, evidence hashes, ledger, and incomplete recovery receipt were unchanged, and the postflight journal had no message or fault.

The result status is `failed`. The result, device evidence, and attempt all keep `authorizes_launch=false`, `authorizes_recovery=false`, and `authorizes_cleanup=false`. These observations cannot authorize normalization, recovery, or another launch.

The scanner source was `0c4f4bc9bd87aa41630349616dbc545d3114018ee93f80ab9c0a82da5f649e79`, the retained-KIQ observer was `cf6513926a9c9fbf5f11df3cd1980ca3de90a786d8ef4c5f21d8764d5755b3d9`, and the recovery helper was `d4e4994885ad8300b89f96ae78a7098e872b64055cc8123146959d2a66c39e21`. `offline-tests.log` records the focused 12/12 fake-transport suite.
