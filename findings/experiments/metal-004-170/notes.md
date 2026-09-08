# metal-004 / candidate 1.0.170

One bounded launch ran on host boot `c3d9b5f0-4f84-432c-9221-b4792a083829` after the
amdgpu-to-vfio handoff with PCI reset methods disabled. Build
`c8328a6c1f75442399b62276ed7d65aa` loaded with all seven SDMA routes validated.

Native hybrid creation, `startHWEngines`, `powerUpHWEngines` and accelerator `powerUpHW`
returned success. KIQ submissions advanced through at least stamp 34. The first localized
hardware failure was an SDMA0 paging timeout: queue 1 retained an enabled indirect buffer at
`0x400100020` with zero bytes consumed and 0x70 remaining. `VM_FAULT_STATUS` stayed zero.

The candidate's address hook observed `0xffbfde011c` in the fixed channel template on every
call, so it never repaired the actual paging address. Offline disassembly after the run traced
the emitted SDMA INDIRECT address to `AMD_SUBMIT_COMMAND_BUFFER_INFO + 0x58 + 0x28*i`.
Candidate 1.0.171 targets that measured producer field.

The critical record buffer reached 128 entries and dropped later records because every
successful KIQ operation was recorded. The coordinator therefore returned `INVALID /
capture_loss` and requested shutdown; the guest did not finish within the remaining deadline,
so the exact container was force-stopped. Candidate 171 caps routine success records while
retaining failures.

Rootless recovery destroyed both PSP rings but found nine active HQD selections. Eight dequeue
requests timed out, eight entries required a forced ACTIVE clear after halting MEC, and both
`CP_STAT` and `CP_CPC_BUSY_STAT` remained nonzero. The recovery receipt is `incomplete`, cannot
authorize warm reuse, and closes this boot to further GPU launches. The host kernel recorded no
fault.
