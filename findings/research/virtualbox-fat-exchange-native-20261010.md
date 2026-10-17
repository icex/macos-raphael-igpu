# Candidate410: VMSVGA registry extraction and natural shutdown

Root-owned software bootG UUID `f9c1de4d-ca93-4a04-a830-a122143c2745`, source
`89db9fb35074bfc276b75d0a5520d184e6c98c1e`, eight CPUs and RealTSCOffset.
No physical GPU/VFIO or Metal acceleration. The native controller result retains
`error_type=VBoxCallError` and automated `guest_boot_qualified=false`; neither was
rewritten to claim an entirely passing controller run.

## Function and framebuffer ownership evidence

Root verified the software desktop and `inventory-status.png`: C410_STATUS0 and
awake assertions at1. The owned awake job was then removed; `awake-removed.png`
shows the job/assertions cleared before shutdown. The short FAT-volume command
succeeded without a large keyboard payload or system-disk extraction.

Fresh IOService evidence identifies GFX0, vendor15ad/device0405, class030000,
PCI bus0/device2/function0. Assigned resources decode as:

| Region | Base | Length |
| --- | --- | --- |
| BAR0 indexed I/O |0x6030 |0x10 |
| BAR1 framebuffer memory |0xe0000000 |64MiB |
| BAR2 FIFO memory |0xe4400000 |2MiB |

GFX0 has active `.Display_boot` / IONDRVFramebuffer with active
IOFramebufferUserClient and IOFramebufferSharedUserClient children. The retained
framebuffer text reports IOFBMemorySize8294400, consistent with1920×1080×4.
This establishes the existing framebuffer attachment and geometry. It is not
exclusive writer ownership, memory-map permission, FIFO capability or accelerated
presentation qualification. A new transport cannot safely assume the boot
framebuffer has relinquished this aperture.

The exchange medium is UUID `3d7a42fb-25a1-43b7-bfe1-d980ace75c59`, port5/device0;
loader/system ports2/4 remain separate. After independently verified stop and
medium closure, root ran stopped-only extraction. The guest receipt passes and
all nine returned fresh-file hashes match. The three requested original409 files
were absent from `/tmp`; **no recovery of original409 registry evidence is claimed**.
Fresh410 evidence replaces that missing observation for this boot only.
The post-run VDI SHA256 is
`ad04490fd4d1de3f8033821fb232fd0bc6a625e769060a83b896556e8fea28b5`.

## Capture/controller error and independent cleanup

Selected retained errors include a0×0 screenshot refusal and the main polling
loop's showvminfo failure during GUI teardown: direct console unavailable,
VBOX_E_INVALID_OBJECT_STATE with outer VBOX_E_VM_ERROR0x80bb0003. The loop's
read-side failure produces the original VBoxCallError. It does not prove that
the guest crashed or that the eventual stop was forced.

Independent VBox events show ACPI S5 at202.287588 seconds, OFF at202.291376,
and TERMINATED at202.343239. Exact-UUID registry absence was confirmed about
79.967 seconds before the300-second deadline. Original cleanup reports poweroff,
unregistered=true, one attempt, exchange_closed=true, no cleanup_error and the
post-run disk hash. These support natural guest completion and medium release,
while preserving the main-loop error. No controller fix is included in410; a
later candidate should handle only this exact transient observation with bounded
identity-preserving reconciliation.

1486 host tests passed,8 skipped (56.230 seconds). The companion manifest hashes
22 bounded artifacts; original private command logs and raw registry remain local.
No source inventory output is treated as proof of full Metal acceleration.
