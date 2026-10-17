# Blocked early-GDB experiment archive

This patch preserves the unqualified `GDB=wait` plus `slide=0` early
`OSKext::start` rendezvous implementation and its offline tests before removal
from the executable toolchain.

It must not be applied or staged. The frozen qualification attempt associated
with `slide=0` ended in OpenCore `StartImage failed` before XNU handoff. Its
software breakpoint was never inserted, so breakpoint-byte corruption does not
explain that failure, but the archived evidence does not isolate `slide=0` as
the sole changed variable. QEMU/KVM breakpoint capacity and a deterministic
KASLR-enabled pre-kext boundary also remain unqualified. See
`../2026-09-10-early-gdb-rendezvous-design.md` for the evidence and address
relocation calculation.

The patch was captured from a shared worktree and includes surrounding context
for the already-retained live-serial-path changes. Those live-serial-path
changes are not part of the blocked experiment and remain in the active tools.
