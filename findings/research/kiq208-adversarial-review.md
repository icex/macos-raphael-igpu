# Candidate-208 adversarial KIQ review

Date: 2026-09-13. Read-only source/log audit; no hardware action.

Candidate-208 evidence is `/home/bogdan/macos-vm/run/candidate-208-results/serial.txt` (the run manifest identifies the mode-3 contained probe). The pre-native sample was `ACTIVE=0, RPTR=0, WPTR=0x20, DEQUEUE=0`; halted setup was logged complete. After native, XQ3 observed `ACTIVE=1`, while XQ2 recorded `EOP=0`, `WPTR=0x20`, `RPTR=0`, `DEQUEUE=0`, and result `0xe00002bc`; the wrapper then recontained MEC with `0x50000000`. The pre/post native MEC values printed as `0`, so this run does not prove whether the halt bits were cleared by native code or whether that read path aliases/does not expose the saved control state. It does prove that native `startKIQ` was entered and that the queue became ACTIVE despite the halted transaction.

## Native call graph and static evidence

X6000 `AMDGFX10KIQHWChannel::startKIQ` is `x6000.asm:0x8e670`. It builds the 0x38-byte native queue parameter at `0x8e69b–0x8e6de`, then calls the hardware interface vtable `+0x2c0` (`0x8e6ea–0x8e6f0`) and dispatches virtual command `8` through the returned object vtable `+0x120` (`0x8e6f3–0x8e706`). It compares returned spec words 0..2 at `0x8e711–0x8e72f` and stores returned pointer state at channel `+0xc0` (`0x8e733`).

The visible X6000 `startKIQ` body does not write MEC, but its command-8 target is HWLibs `_gc_create_kiq_queue_10_3`, whose MEC write is explicit at `0x1501e–0x1506e`, before any EOP/MQD/PQ programming (`0x15077` onward). It reads register selector `0xf55` (`0x1501e–0x15039`), derives a mask from context byte `hw+0x320`, then writes the result back (`0x15042–0x1506e`). Specifically, `r12d = 1` only when `byte[hw+0x320] == 0`; after shift by 28 and OR with `0xafffffff`, the mask is `0xbfffffff` for zero context or `0xafffffff` otherwise, and is ANDed with the current CP_MEC value. Both masks clear bit 30; the nonzero-context mask also clears bit 28. These are the MEC/ME halt bits. Thus native `startKIQ` is expected to unhalt MEC as part of the HWLibs queue-create command, even when the caller entered with MEC halted. This directly explains candidate-208’s post-native `ACTIVE=1` and printed `MEC=0`; it is not an unresolved selector/diagnostic side effect.

The same function then proceeds to the queue image and EOP/PQ programming, so “native preserves MEC halt” was a false design assumption. XQ3’s selector reads showing `ACTIVE` changing from 0 to 1 while EOP stays zero are consistent with this exact order: HWLibs clears halt first, activates the queue path, then later programming fails or is rejected. The containment wrapper’s post-return `0x50000000` write is therefore necessary, but it occurs after the native unhalt window.

## Discriminating next capture

The next diagnostic should break at HWLibs `0x1501e`/`0x1506e` and capture the pre-read value, `byte[hw+0x320]`, derived mask, and write result. A watchpoint remains useful for confirming the mapped register address, but the static sequence already proves a native unhalt write. Capture the first post-write HQD/EOP values separately; do not infer that MEC remained halted from the wrapper’s pre-call state.

Do not treat the mode-3 result as KIQ success or retirement: `ACTIVE=1` and `EOP=0` with result `0xe00002bc` is a contained native failure. Preserve the current failure path that reasserts MEC halt (`0x50000000`) before returning.

The generic HWLibs `gc_create_queue` at `0x85c0` remains a separate backend dispatch, but it is not the relevant native KIQ path. The relevant `_gc_create_kiq_queue_10_3` writer above is now resolved and is the concrete source mechanism for the MEC transition.
