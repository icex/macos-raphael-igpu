# Live status — 2026-10-10 — paused by user

Candidate 417 (`049c6c6`, BootI UUID `9e78680e-d59b-475c-80ef-670a0be43b93`)
was interrupted by the user-requested pause during boot. No desktop or root relay
response was qualified. Controller helper forced poweroff, then the original
controller unregistered the VM on its first attempt and finished without a
reported cleanup error. Service inactive; no physical GPU exposure. This is not
clean guest shutdown. [Report](findings/research/virtualbox-relay-pause-20261010.md).

Final local suite: 1496 tests ran, eight skipped, all remaining tests passed.
The process/log ownership fix is committed but still needs a complete native run.
Last physical GPU run remains candidate 402 with its recovery receipt unchanged.
Host awake inhibitor remains active; no request to suspend the machine was made.

Published dev `0ecc171` has passing hosted test and macOS build jobs (run
37998445036). Main remains `861ba5e`. Candidate 418's isolated patched VBox
production build passed; it was not installed or run. PGM backing leases,
reset/teardown safety, exclusive framebuffer ownership and VBox Metal remain
unqualified. Candidate 420 records source-analysis resume points only.

Candidate 419 integrates 415–418 and the source-only 420 pause report. The exact
tested 402 kext/manifest remain unchanged. Its independent build audit reverified
57 artifact entries and reproduced both compiled VFIO source files by zero-fuzz
patch application. Extracted tests substitute PGM and map calls; they do not
qualify DMA lifetime or physical passthrough.

Resume only on user request: finish the bounded relay native test in a fresh
candidate/clone, then qualify framebuffer ownership; separately implement and
exercise the PGM-owned backing lease before connecting physical DMA.
