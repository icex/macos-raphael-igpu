# Candidate 409: stock VMSVGA discovery run

**Completed and stopped.** Root owned all VM and guest interaction. Source `9a02f8a`,
explicit graphics controller `vmsvga`, 3D disabled, no physical GPU/VFIO and no
network adapter. BootF uses independent reflinks of cleanly stopped 406 bootE.
No Raphael Metal or immutable snapshot transport qualification is claimed.

## Observed so far

Root observed the actual macOS desktop at approximately 107 seconds and an active
Terminal. The root-viewed `framebuffer.png` shows UserIsActive,
PreventUserIdleDisplaySleep and PreventUserIdleSystemSleep assertions at 1.
The read-only IOFramebuffer conformance output was saved in the guest as
`/tmp/c409-framebuffer.txt`; host extraction and interpretation remain pending.
This does not yet establish a particular PCI framebuffer ancestry or ownership.

The first 1308-byte keyboard command injection timed out after 15 seconds and
left partial shell input. Root interrupted that incomplete command with Ctrl-C.
The retry with a 45-second allowance executed but crashed with AttributeError
(str has no get): this guest returns an ioreg plist dictionary root, while the
original helper expected an array. The original failure screenshot is retained.
Root separately saved the raw 2144152-byte ioreg plist and conformance text.
The fallback screenshot explicitly shows Display_boot / IONDRVFramebuffer
registered, matched and active; this is attachment evidence, not exclusive ownership.
The offline helper now accepts dictionary or list roots and rejects other schemas;
this fix is not yet guest-qualified. The initial
attempt is **not** successful execution of the inventory, and no empty/partial
output may be used as evidence of absent framebuffer ownership.

## Inventory limits and final lifecycle

The compact plist inventory is a heuristic filter with explicit property
allowlisting. It must be cross-checked against `ioreg -r -c IOFramebuffer`, because
class-name matching alone can miss subclasses. Even a complete ancestry tree
does not establish exclusive ownership or permission to write registers/FIFO.

Stopped-disk 7-Zip inspection reached the GPT listing with a roughly 274 GB
`1.apfs` member; no whole APFS image was extracted. The raw 2144152-byte registry
and conformance text remain guest-only. Successful corrected heuristic inventory
is **not** claimed. A small isolated FAT exchange disk is the next transfer
experiment; no NIC, GPU or bulk APFS extraction is needed.

Initial `awake.png` did not yet show the assertions because of a startup race;
later `framebuffer.png` supplied the positive awake observation. Root removed the
owned awake job and verified NO_CAFFEINATE before shutdown. VBox records S5 at
257.041716 seconds, OFF at 257.044244 and TERMINATED at 257.085832. Original result
is poweroff/unregistered=true with one attempt and no cleanup error. Independent
root verification finds the exact UUID absent about 18 seconds before deadline.
Retained UART has no panic()/non-monotonic-time marker. No forced shutdown or
successful transient-retry branch is inferred.

After the root-schema fix, the integrated host suite passed 1480 tests with eight
skips in 56.132 seconds (`run/c409-root-schema-full-suite.log`). The fix itself
has not run in this guest. Current published dev is 59422dae6683550b7027dd8fe53fb7801f33bbcd,
with hosted test/build success and release skipped in Actions 37995939729. Main
is unchanged; this candidate's new findings remain local until delivery.
