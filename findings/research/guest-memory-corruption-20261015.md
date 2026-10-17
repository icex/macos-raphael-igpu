# Guest corruption investigation — 2026-10-15

Priority is guest corruption before audio. Baseline: remote `dev` 319a2dd, host boot
`ee006810-2a60-4378-b4de-8d673b8c3f00`, kernel 7.2.10-1-cachyos-bore, Ryzen 7 9800X3D,
microcode 0x0b404035. Host configuration was unchanged in the initial controls;
the continuation separately records the later bounded IH register cleanup.
GPU-less trials use the compatibility
refresh path, `Haswell-noTSX`; no VFIO exposure or GPU ledger entry. RAM was automatic:
14 GB in baseline-02, 15 GB in finite-tlb and plugin-off trials; all used 8 vCPUs.
Subsequent trials pin RAM explicitly and verify the container configuration.

**Update: orphan display IH DMA is the leading mechanism; permanent fix unqualified.**
The continuation below found AMD IH records in host cached-file corruption and the
earlier TCG core, then observed the unowned iGPU's IH0 ring still advancing after
QEMU exit. A bounded in-place IH stop contained that DMA path on this boot. This
is not yet complete physical-page attribution, a diagnosis of every panic, or a
delivered teardown/recovery fix. Earlier GPU-less trials did not exclude DMA left
active by a previous GPU owner.

Integrity failures reproduce with RaphaelGPU disabled, Lilu disabled,
THP disabled, NVMe instead of AHCI, one vCPU, and an isolated macOS 15 image. None
of these changes is a sufficient fix. The later 8 GB failure had zero observed QEMU
VmSwap. The software-emulation comparison is limited by a QEMU process crash; it
does not yet establish whether the guest corruption requires KVM.

Stopped system disk backed up with a required reflink to
`~/macos-vm/backups/mac_hdd_ng-before-memory-diag-20261015.qcow2`. Configuration and both
boot images saved under `~/macos-vm/run/memory-diag-20261015/`. Evidence below is in that
directory unless a full path is given. Diagnostic launch variations retain the ordinary
GPU-less image/identity checks and bounded user service. Failed guests are frozen for evidence
and force-stopped; this is not a clean shutdown or a GPU recovery result.

## Observed

- `baseline-01`: boot, image collection, acknowledged native shutdown and seal succeeded.
  Its late-attached serial and running register/RAM samples show no crash.
- `baseline-02`: reached userspace, but backgroundtaskmanagementd and storagekitd crashed
  with general protection faults (both report guest CPU 6). The compatibility SHA gate
  then rejected the uploaded BootKC. Other historic system crashes involve guest CPUs 1
  and 5 as well; this does not isolate CPU 6 or a host physical core.
- The rejected BootKC differs from baseline at exactly four bytes at offset `0x6d5000`,
  the start of a 4 KiB page: `8d 4a 28 48` became `40 c1 00 00`. The guest-reported SHA
  still equals the intact baseline, while the received file has a different SHA. The
  uploaded SystemKC and both userspace text images are identical to baseline. See
  `baseline-02-artifact-comparison.json` and the two retained IPS reports.
  Good upload nonce `bad0c19d5004460e9c329d7375b59222`; failed nonce
  `862cc729f6ce4b9999e8f7ec69b7c7bd`, under `~/macos-vm/run/upload/compat-*`.
  This observes transient data disagreement; it does not alone locate the corrupting write.
- `finite-tlb-01`: boot/capture/native exit succeeded. Its argument `tlbto_us=10000000`
  produced a live `_TLBTimeOut` of `0xa817c80000` ns (~722 s), **not 10 s**. XNU casts
  the nanosecond result to uint32, then inflates it by `2^vti`; this trial cannot establish
  absence of shorter TLB stalls.
- `finite-tlb-02`: `tlbto_us=19531 vti=9` read back as `0x25409f000` ns
  (9,999,872,000 ns). APFS first reported compressed-data verification failure at
  inode 10819, offset 39550976, during chronod page-in. The first panic at uptime
  39.64 s was `pmap_pv_remove: null pv_list`, mDNSResponderHelper, CPU 0. Nested debugger
  faults followed. Both serial and the first-panic RAM extraction retain the initial
  backtrace; the first fault was not an IPI timeout.

- `no-rgpu-01`: `-rgpuoff` removed plugin initialization; boot/capture/native exit passed.
- `no-rgpu-02-canary`: plugin still disabled, but APFS reported a compressed-data hash
  mismatch at inode 10811 / offset 385777664 **before** the canary started. The later
  canary completed 47,934 remaps / 98,168,832 page checks with zero mismatches, all four
  image checks passed, and native shutdown/seal succeeded. This is an integrity failure
  despite success in those separate checks. A different inode/offset from finite-tlb-02
  also weakens a single persistently damaged compressed block as a complete explanation.
  Current source text at the earlier BootKC upload mismatch location was intact in a
  live kernel-text snapshot; the earlier upload mismatch was not reproduced there.

- `one-cpu-01`: pinned 15 GB, eight actual vCPUs (intended one-vCPU override was not forwarded), plugin-off, standard IRQ chip. A system-process
  crash storm preceded `Taking non-sleepable RW lock with preemption enabled`, in
  APFS getattr / NotificationCenter. Evidence capture stopped the failed guest at 55 s;
  native exit/seal did not occur. The intended single-vCPU override was not forwarded by systemd; no cross-vCPU IPI conclusion follows.
  A snapshot of XNU's complete `__TEXT` has exactly the same differing byte locations
  versus the intact BootKC as the prior live snapshot (234 bytes / eight symbols outside
  the header). There were no additional changed locations in that captured XNU segment;
  this does not validate kext text, data structures or CPU translation-cache contents.

- `thp-off-01` was an invalid THP A/B: the initial diagnostic image build failed and
  systemd did not inherit the image override. The actual original-image / eight-vCPU
  guest again had APFS integrity errors and a rejected SystemKC upload. That upload
  differs from the intact baseline by 972 bytes; the guest's hash also differs from
  baseline and from the upload. See `thp-off-01-actual-control-artifact-comparison.json`.
  It is further original-image corruption evidence, not THP-off evidence.
- The diagnostic launcher was corrected to forward IMAGE, RAM_GB, VCPUS and DISK_BUS
  explicitly into the transient service and retain an expected/observed configuration
  check. `one-cpu-02-configuration-check.json` plus actual QEMU argv verifies the first
  **actual** single-vCPU trial at 15 GB. Earlier labels are retained without rewriting
  their raw evidence. The false single-vCPU conclusion was retracted.

- `one-cpu-02`: expected/observed settings and actual argv verify one vCPU, 15 GB,
  original pinned image. It panicked after ~154 s: `kernel stack overflow`, stack depth
  `0x4321cd70` with inconsistent stack addresses. Serial contains the first panic;
  no seal/native exit occurred. This is the valid single-vCPU failure, independent of
  the earlier mislabeled attempt.
- `thp-off-02`: the intended image did run, but relocated QEMU failed to locate firmware
  ROMs; no macOS verdict. The wrapper was corrected to use the original firmware directory.
- `thp-off-03`: pinned diagnostic image 04c893a9, original QEMU executable SHA
  `bf7a8b373cda802d5b63dc162fee9cbf4698a5920b50d9a993458c676ecdafa3` unchanged;
  verified 15 GB / eight vCPUs / AHCI, `THP_enabled=0`, `AnonHugePages=0`, still THP=0
  at 7+ GB RSS. Boot, 47,541 remaps / 97,363,968 page checks, image SHAs and native
  exit passed, with no recorded APFS mismatch or panic.
- `thp-off-04`: same verified settings and live THP=0, but APFS rejected a dyld shared
  cache page (inode 10813 / offset 99876864). Thus per-process THP disable is insufficient;
  the earlier clean trial must not be promoted to a fix. Other outcomes remain separate.

- `thp-off-04` later passed its canary, image checks and native shutdown despite the
  earlier APFS integrity failure. This is why a successful compatibility seal does not
  establish a healthy boot or general memory correctness.
- `nvme-01`: same pinned image / 15 GB / eight vCPUs / plugin-off / THP=0 as thp-off-04,
  with only the system disk controller changed to QEMU NVMe. Actual argv verifies the
  controller. Boot, canary, image checks and native shutdown passed, with no recorded
  APFS integrity error or panic. One pass is not a controller-fix verdict.

- `nvme-02`: the same verified NVMe / THP-off / 15 GB / eight-vCPU configuration
  panicked in `pmap_pv_remove: null pv_list`, CPU 4, before canary/image collection.
  Failed guest force-stopped after first-panic capture. NVMe is insufficient; the
  earlier successful NVMe boot was not a reliable fix.

- `no-lilu-01`: explicit Lilu-disable log and live XNU snapshot restore original bytes
  at `_kernel_trap` and two OSKext hooks; the separate bootstrap patch remains.
  VirtualSMC falls back to legacy/gen1 mode, so this is a framework/SMC variation.
  Boot, canary, images and native exit passed without recorded integrity errors.
- `no-lilu-02`: same verified VM settings and Lilu disable, but APFS rejected a shared
  cache page (inode 10813 / offset 191397888). Canary, image checks and native exit
  later passed. Lilu disable is insufficient. Upstream Lilu 1.7.2 has an independently
  relevant [address-slot overrun fix](https://github.com/acidanthera/Lilu/commit/e4748cc081bf060302c7d3c44a643ce1d11b7e1d),
  but this is not demonstrated to explain corruption with Lilu disabled.

## Independent macOS 15 clone and interrupt controls

The stopped rollback source `~/macos-vm/rollback/macos-15.8.1-24H32.img` was reflinked
into `memory-diag-20261015/sequoia-vm/mac_hdd_ng.img`. Its original image and the active
Tahoe disk were not used for the clone trials. The clone has separate configuration,
boot images, run directory and agent servers. All clone trials disable RaphaelGPU
and Lilu and use NVMe with THP disabled. Their artifacts live under
`memory-diag-20261015/sequoia-vm/run/memory-diag-20261015/`.

- `sequoia-01`: verified macOS 15.8.1 / 24H32, 15 GB, eight vCPUs. Canary passed
  50,834 remaps / 104,108,032 checks, but the guest and received SystemKC SHAs differed.
  Other images matched. No seal; failed guest force-stopped. See
  `sequoia-image-mismatch.json` in the main evidence directory. This rejects
  a Tahoe-only explanation, without proving a shared cause for every failure.
- QEMU 10.1.2 refuses KVM with a userspace APIC. A diagnostic-only source copy changed
  `apic_get_class` to select the existing userspace class, retaining other checks.
  Build source, one-function patch, binary hash and image are retained outside the
  repository in `qemu-user-apic/`, `qemu-userspace-apic-diagnostic.patch` and
  `user-apic-image/`. No production binary or image was replaced.
- `apic-kernel-control-01`: that diagnostic binary with ordinary kernel APIC, 15 GB,
  eight vCPUs. Monitor confirmed KVM and eight `kvm-apic` objects. Guest page-fault
  panic at ~46 s; no collection/seal, force-stopped after capture.
- `apic-userspace-01`: same image and settings with `kernel-irqchip=off`. Logs show
  userspace APIC selection, but no firmware serial and an unresponsive monitor.
  Manually force-stopped after ~154 s, then collector terminated. **No macOS or AVIC
  verdict.** No host module parameter was changed.
- `ram8-01`: ordinary kernel APIC, 8 GB, eight vCPUs. APFS reported two different bad
  hashes for the same compressed-stream offset (437157888), then `Using inactive port`
  panic at uptime 39.82 s. Host sampler: peak QEMU RSS 8,105,600 KiB and VmSwap=0 in
  every sample. This failure does not require 15 GB or observed QEMU page swapping.
  No seal; force-stopped after first-panic capture.
- `tcg-01`: 8 GB, eight vCPUs, diagnostic binary, `-machine accel=tcg`. Monitor verified
  KVM disabled. It reached userspace without a recorded APFS error or guest panic,
  then **QEMU itself segfaulted** at host 01:52:54 (+03:00). Service exit 139; no canary
  result, image capture or native shutdown. Collector was terminated after confirming
  the container had already exited. Its returncode -15 describes that termination,
  not QEMU's exit. Core and matching container libraries were retained. GDB identifies
  `tb_tc_cmp` in `tcg/region.c:154`, dereferencing noncanonical pointer
  `0x87b11cbc80005704` supplied by `g_tree_lookup`. See `tcg-01-qemu.core`,
  `tcg-01-qemu-gdb-sysroot.txt` and `tcg-01-service.log`. The initial separate-TCG-defect
  interpretation is superseded by the exact IH overwrite evidence below. This
  run still cannot independently clear KVM or attribute every guest failure.
- `tcg-one-01`: eight GB, one software-emulated vCPU, original QEMU executable
  behind the THP-disable wrapper. The configuration check and service journal
  confirm the effective single-vCPU argv; the monitor records KVM disabled.
  This trial is **finished**, not still collecting: service
  `rgpu-compat-plain-83023c079eae` reached its 6000-second limit on
  2026-10-15 at **00:40:23 UTC** and QEMU terminated on signal 15. Captured serial
  reached userspace without a recorded integrity error or first panic, but there
  is no guest-command response, completed canary, image collection or native
  shutdown proof. The collector left no final summary; its early container
  snapshot is not current state. This timeout gives no clean KVM comparison.
  Journal retained as `continuation-01/tcg-one-01-service-final.log`.

## Continuation: ownership reconciliation and direct KVM controls

At 06:48:36 UTC, the same host boot had no QEMU process or macOS container;
only `rgpu-inhibit` remained. No process was stopped or signalled by this
continuation. The separate container started at 06:27:28 UTC was desktop release
514, attempt `d20261015092721`, CID `53f85e68e40eee5b84b73fe03f7b0e227f66ca5e709b003020b7e1c85889736f`.
Its user-service journal records exit at 06:35:42 UTC, before this continuation.
The attempt's verdict is INVALID, shutdown says `already-stopped`, and the
separate recovery receipt says recovered / `authorizes_launch=true`. Those
artifacts do not establish native guest shutdown. This external GPU exposure
must not be attributed to the GPU-less corruption investigation.
See `continuation-01/initial-state.json`,
`continuation-01/external-desktop-service-journal.log` and the original attempt
results under `~/macos-vm/run/`.

Two upstream KVM selftests were built from local upstream revision
`238650ef6c7c7cca08e032527329424c9fbd70e5` in an isolated extracted tree; the
reference checkout was unchanged. Build used installed UAPI headers and
`LIBVFIO_O=` to omit unrelated VFIO-library objects. Neither test uses QEMU,
OpenCore, macOS, guest disks or passed-through devices. Each ran in its own
user service with a 120-second deadline, 2 GiB memory cap, zero allowed swap,
nice 10, and a 200% / 400% CPU cap respectively.

- `set_memory_region_test 10`: passed, exit 0, 31.029 s, 274.3 MiB peak,
  no swap. Forty total move/delete iterations checked guest-observed values
  with the slot-zap quirk enabled and disabled. Guest-memfd cases were skipped.
- `mmu_stress_test -c 4 -m 2 -s 1`: passed, exit 0, 2.670 s, 1 GiB peak,
  no swap. Four vCPUs exercised CR0.WP context reset, read-only invalidation,
  expected write faults, writable restoration and teardown. This is an MMU
  fault/invalidation control, not a general byte-integrity test.

Logs, extracted unmodified test sources, build log and revision are under
`continuation-01/`. These passes do not clear KVM or hardware; their short,
synthetic workloads lack the failing macOS translation/device paths.

### Fresh macOS 15 control and exact upload comparison

`continuation-01/pcid-control-01` was a fresh required reflink of the rollback
source, with the earlier clone's separate OpenCore/config. Eight vCPUs, 8 GB,
NVMe, THP=0, Lilu/plugin off; no host device ownership operations. Only /dev/kvm
was attached: no VFIO, DRI or TAP, and only the NAT vmxnet3 NIC. A unique name
and ports separated it from desktop ownership. Effective QEMU argv and live
CPU-state artifacts were captured independently of the collector's PID-1
snapshot (PID 1 can be the shell, not QEMU).

All eight vCPUs had CR4 `0x1406e0`, **PCIDE clear**, in userspace and again in
the frozen failure capture. Thus the proposed PCID-off intervention was
cancelled as non-discriminating. This control nevertheless failed the SystemKC
identity gate: guest SHA `2296155f1f12471e7b774020ba70d9fb487d02224c1f85d373130511969c2243`,
received SHA `186ea5089552276da9e2f824d6ca97b3a5edee21e7eb1b5860a70df6c1f55bec`.
Canary: 48,943 remaps / 100,235,264 checks, zero mismatches. No recorded APFS
integrity error or panic in this trial. Evidence capture completed, then the
failed named guest was frozen and force-stopped; no native shutdown or seal.
Active PCID tagging, the second NIC and host GPU-node exposure are not needed
for this image disagreement. It does not establish the cause of earlier APFS
failures/panics, nor exclude all guest invalidation paths.

Comparing its 373,112,832-byte SystemKC upload against `sequoia-01` finds only
two differing page-start words. Selecting intact pages from the two copies
produces a whole-file SHA **exactly equal to the independent guest reports**
above. Against that verified reconstruction:

- `sequoia-01`: at `0xb22c000`, `00 00 00 00` became `40 e3 01 00`.
- `pcid-control-01`: at `0xa2a2000`, `00 00 00 00` became `e1 59 09 00`.

Both disagreements change three bytes of a four-byte aligned word at a 4 KiB
boundary. Earlier Tahoe BootKC changed all four bytes at a page boundary.
This observes sparse transient disagreement; it does not locate whether the
write happened in source data, a userspace upload buffer, kernel/NIC transport,
or receiver/host memory. Reconstruction was offline: it did not replace an
identity artifact or relax the compatibility gate. See
`continuation-01/sequoia-systemkc-upload-differences.json` and
`continuation-01/systemkc-24h32-reconstructed-sha-verified.bin`.

### Instrumented transfer control

`transfer-01` used another fresh reflink and the same verified eight-vCPU/8-GB,
single-NAT-NIC topology. The guest reports curl 8.7.1. Upstream
[8.7.1 option handling](https://github.com/curl/curl/blob/curl-8_7_1/src/tool_getparam.c#L1033)
loads `--data-binary @file` with `file2memory` and copies into the POST buffer;
the [upload read callback](https://github.com/curl/curl/blob/curl-8_7_1/src/tool_cb_rea.c#L43)
reads file data in chunks. These source paths motivate a buffer/streaming
comparison; they are not an assertion that Apple's binary has an identified bug.

One boot performed buffered curl, a small C uploader, streaming curl, buffered
curl again, then the ordinary compatibility uploads. Each extra SystemKC
upload had a distinct permit/nonce and immutable host artifact. The C uploader
read the entire file into one allocation, calculated CommonCrypto SHA256 before
and after sending that same buffer, and compared against the file's independent
shasum. Host hashes were checked separately; any extra-upload disagreement
rejects the diagnostic before sealing. Original image gates were retained.

All five 373,112,832-byte SystemKC uploads matched the known SHA. C buffer
before/after and repeated guest file hashes matched. Canary: 49,989 remaps /
102,377,472 checks, zero mismatches. No recorded APFS integrity error or panic;
image checks and acknowledged native shutdown with exit 0 passed. This is one
clean instrumented boot, not a fix or transport/guest-memory qualification.
Evidence: `continuation-01/transfer-01/run/transfer-report.json`,
`compat-94cf8b72e77248018d91acc32366593f-output.txt`,
`guest-identity.json` and the per-trial serial/configuration artifacts. Diagnostic
source and exact input hashes are retained under `continuation-01/`.

`transfer-02` repeated that workload on another fresh rollback reflink. The C
buffer matched the reference SHA before **and** after sending, and the guest's
repeated file hashes matched. Its received file initially hashed to
`77f7b41d3f1039ed14aa9e7e8d94a597bac7c2b97661e6e09b609c6a99601674`.
The other four SystemKC uploads matched. Canary passed 50,276 remaps /
102,965,248 checks; no recorded APFS integrity failure or panic. The extra-upload
gate rejected the diagnostic before seal; evidence was captured and the exact
named GPU-less guest was force-stopped, not natively shut down. This rejects
curl's large-buffer handling as a necessary cause of this upload disagreement.

### Host cached data changed after the guest exited

After `transfer-02` and all QEMU processes had exited, subsequent reads of its
C-upload artifact returned **different whole-file hashes**, while inode
10617224, size 373,112,832, mtime_ns 1792047781229735094 and ctime_ns
1792047781249735117 stayed fixed. Independent sha256sum confirmed the changing
buffered-read result. A reflink snapshot instead returned the original received
SHA above. `O_DIRECT` reads of the original and both read methods on the
snapshot matched that original SHA. The reconstructed reference matched its
known-good SHA through both read methods. The files have NOCOW (`C`) attributes.

A ten-sample watch saw changing read/mmap hashes with unchanged metadata and
no IN_MODIFY/IN_ATTRIB/IN_CLOSE_WRITE/IN_DELETE_SELF/IN_MOVE_SELF events. lsof/fuser
found no visible writer; lsof noted inaccessible container filesystem metadata,
so these process/event checks alone do not rule out every possible writer.
The direct/cached difference is the observation; the precise host corruption
path is not established by filesystem timestamps alone.

Raw evidence: `host-artifact-watch-01.json`,
`transfer-02-poststop-host-hashes.json`,
`transfer-02-buffered-versus-direct.json`, and the frozen snapshot
`transfer-02-systemkc-frozen-copy.bin`, all under `continuation-01/`.
The snapshot differs from the known-good reference in 1,521 bytes, including
structured records near file offset `0x9acd160`.
`transfer-02-on-disk-exact-differences.json` compares the stable on-disk/snapshot
state. The earlier `transfer-02-exact-differences.json` records a different
cached-read state; do not conflate their hashes. Older Tahoe, Sequoia and
pcid-control artifacts still had their original bad SHAs through both read
methods (`prior-artifact-buffered-versus-direct.json`); the old differences
were not all merely transient cached-read discrepancies.

### Structured overwrite: AMD display IH records, including the TCG core

Using Linux revision `238650ef6c7c7cca08e032527329424c9fbd70e5`,
`amdgpu_ih_decode_iv_helper` decodes each eight-DWORD record as client/source,
ring/VMID, timestamp, PASID and four source-data words. The payload header
`0x80005704` decodes as client **4** (DCE/DCN), source **0x57**, ring 0, VMID 0,
VMID-source 1. AMD's DCN source header names 0x57
`OTG0_IHC_V_UPDATE_NO_LOCK_INTERRUPT`. Forty consecutive sampled records decode
coherently. Timestamp deltas alternate 208,332/208,336 ticks, consistent with
120 Hz **if** the clock is 25 MHz. This rate interpretation is conditional;
the raw format/source identification is independent of that clock assumption.

The original TCG bad pointer `0x87b11cbc80005704` is not just a coincidental
matching word: core offset `0x19eb0b20` / host VA `0x7f1164875b20` contains that
exact eight-byte value amid consecutive 32-byte records with the same IH
header, timestamp high word 0x3d, zero PASID and coherent source data. Thus the
generic earlier "possibly a separate TCG defect" interpretation is superseded
by concrete matching overwrite evidence. It still does not clear all KVM paths.

Evidence: `display-ih-payload-decoding.json`,
`tcg-core-exact-bad-pointer-payload.json`, the original core/GDB capture, and
saved source/headers under `ih-source-audit/`. The first restricted
`tcg-core-display-ih-clusters.json` scan missed the separate host allocation;
that negative limited scan must not override the exact-value search result.

### Read-only attribution and bounded IH containment

At 07:18:05 UTC, with no macOS/QEMU process, a temporary container read BAR5
through a **read-only sysfs mapping**, not VFIO. Only required read capabilities
were granted; no device reset, rebinding, IOMMU change or kernel setting changed.
Source offsets/masks are saved OSSSYS5 definitions and Navi/Sienna OSSSYS base
0x10a0. Observed on iGPU 0000:7b:00.0:

- IH0 control `0x1033011f`: ring DMA, interrupt delivery and writeback enabled;
  MC_SPACE=1, ring size 131,072 bytes.
- Ring bus address `0x11f6e000`, writeback address `0x11cf0000`.
- Raw WPTR advanced `0x927e1 -> 0x92961 -> 0x92ae1` at 0.1 s intervals:
  384 bytes / 12 records per interval. Low overflow/may-overflow flags explain
  the raw pointer's unaligned low bits. Secondary rings were disabled.
- IOMMU group 31's **default** domain type was **identity**. This sysfs file
  reports `group->default_domain->type`, not the currently attached VFIO domain
  (Linux `drivers/iommu/iommu.c:iommu_group_show_type`). The return to that
  default after the last VFIO owner closes is inferred from the VFIO lifetime
  source, rather than measured through this sysfs file. Driver remained vfio-pci,
  power/control=on, PCI command=3. Bus-master clearing alone had not stopped IH.

The current artifact-page PFN sample did **not** directly match the ring bus
address. Exact physical-page/translation attribution remains open; do not claim
that it was proved merely by matching the record format. Nevertheless the
active orphan iGPU IH path, matching host overwrite signature and old core are
a much stronger lead than CPU-count, kernel timing or parked-CPU inference.

Source audit found no IH shutdown/verification in `vfio-recover.py` or the
no-queue recovery path. Linux `navi10_ih_irq_disable` disables all enabled IH
rings and interrupt delivery before freeing their memory; writeback has its
own enable bit. Existing GC/SDMA/PSP recovered receipts do not establish IH
quiescence or complete DMA safety.

At **07:22:51 UTC**, under `run/experiment.lock` and fail-closed boot/device,
binding, power, no-QEMU, PCI-command and exact-register checks, the bounded
`quiesce-ih-inplace.py` cleared only mask `0x20101` (RB_ENABLE,
ENABLE_INTR, WPTR_WRITEBACK_ENABLE) from IH0 control:
`0x1033011f -> 0x1031001e`. Posted readback matched; WPTR then read `0x1` in all
eight samples at 0.1 s spacing. The script issued no reset, PCI/config write,
VFIO open, binding or host KVM change. Secondary IH rings/self-update were
already disabled. Its immutable receipt explicitly has `authorizes_launch=false`;
it neither replaces a normal recovery receipt nor qualifies future GPU reuse.

Receipt and command: `ih-quiesce-01.jsonl`, `ih-quiesce-01-command.json`;
prior read-only state: `igpu-ih-readonly-01.json`. This containment does not
repair data already overwritten in guest RAM, host cache or persisted files.
No intentional re-enable of the harmful orphan state was performed.

### Bounded validation after IH containment

The original bad artifact's cached SHA remained fixed in eight initial samples,
then all 25 samples spanning at least 120 seconds (`host-artifact-after-ih-stop-01.json`
and `host-artifact-after-ih-stop-120s.json`). The fixed hash is still corrupted;
no claim is made that disabling IH repaired existing cache contents. These
checks overlapped the new GPU-less workload, not an otherwise idle-host control.

Two independent fresh rollback reflinks then used the same verified eight-vCPU,
8-GB/NVMe/THP-off/Lilu-off settings and single NAT NIC:

- `transfer-03-after-ih-stop`: repeated the instrumented transfer workload.
  All four extra SystemKC uploads plus ordinary image collection matched;
  C buffer before/after and file hashes matched. Canary, no recorded APFS
  integrity error/panic, acknowledged native shutdown and successful seal.
  Full trial elapsed 137.29 s.
- `control-02-after-ih-stop`: matched the original `pcid-control-01` workload
  without the extra transfer instrumentation. Canary: 50,192 remaps /
  102,793,216 checks, zero mismatches. All four image checks matched, with no
  recorded integrity error or panic; acknowledged native shutdown, exit 0 and seal.

Per-trial `run/guest-identity.json` records native shutdown with exit 0 and the
nonce-bound acknowledgement. Serial, configuration and raw results remain in
each trial's `run/memory-diag-20261015/`. These passes strengthen the orphan-IH
lead and validate the bounded contained state. They do not establish that every
earlier panic shares this cause, qualify a future GPU lifecycle, or make the
current recovery implementation complete. No production launcher/kernel/kext
fix has been implemented or published by this continuation.

## Corrections to prior interpretations

`tlbto_us=0` suppresses the timeout panic but still waits for other CPUs to acknowledge
TLB invalidation; it does not skip the invalidation and continue. Seven parked CPUs after
a panic do not establish that a lost IPI caused it. See Apple's
[TLB wait loop](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/x86_64/pmap.c)
and [timeout initialization](https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/i386/machine_routines.c).
The live Tahoe timeout readbacks above verify the parameter behavior in this guest.

GPU-less does not mean RaphaelGPU is disabled: `baseline-02-serial.txt` records its
initialization, diagnostic threads and Lilu callbacks. The plugin-off repeat still logged APFS integrity failure, so that failure does not require
RaphaelGPU initialization. No accelerator was attached in these trials.

A failed refresh does not always mean a failed boot. The earlier d20261015000012 run
already produced successful `RGPU_COMPAT` output and then timed out during shutdown.
Keep boot, image integrity, shutdown and GPU recovery outcomes separate.

The 2026-10-12 package update also upgraded amd-ucode. Comparing cached 20260810,
20260910 and 20260916 packages finds their entire family-1Ah microcode blob byte-identical,
including the active 0x0b404035 patch. See `microcode-package-comparison.json`. The package
upgrade did not change this CPU's microcode. Kernel timing remains correlation, not proof.

## Read-only host audit and bounded userspace checks

The loaded `kvm_amd` GNU build ID matches the installed module:
`3ee38dc6a02ceffdbf42234a1b7009e952f8e278`. Disassembly of
`svm_flush_tlb_gva` tests `npt_enabled`; its NPT branch calls `svm_flush_tlb_asid`,
while only the non-NPT branch executes INVLPGA. This is the behavior of upstream
[26505e1b5b54](https://github.com/torvalds/linux/commit/26505e1b5b546e2fa9a0296b951ca158460c72d8).
See `running-kvm-amd-identification.json` and `running-svm-flush-tlb-gva.txt`.
The current failure cannot be explained simply by this particular workaround being
absent. This does not verify every TLB path or eliminate other KVM defects.

A [kernel-list report](https://lists.openwall.net/linux-kernel/2026/10/02/1622) discusses
host INVLPGB/TLBSYNC corruption separately from KVM INVLPGA. The current kernel has
CONFIG_BROADCAST_TLB_FLUSH=y and no `tlbi=ipi` boot argument; those observations alone
do not prove the erratum occurs here. No boot option was changed.

- Our narrow canary on the host: 30 s, 102,419 remaps, 209,754,112 checks, zero
  mismatches (`host-canary-01.json`).
- Unmodified [upstream userspace reproducer](https://gist.github.com/mfleming/ca26ad3f8d65a12d23d62fb176480fc1)
  at revision `3192288041f8c634d37db586db91624cc482308f`: four rounds, eight jobs,
  five seconds/job, eight readers, two mutators, 512 slots. User service limits:
  2 GiB RAM, 400% CPU, nice 10, 120 s deadline. All rounds completed without a
  mismatch or unexpected SIGSEGV; service exit 0, 20.15 s, 266.2 MiB peak, no swap.
  See `host-upstream-repro-01.log` and retained upstream source/metadata.

These are negative short probes, not host memory qualification. They ran concurrently
with the one-vCPU TCG trial; that trial is therefore not an otherwise idle timing A/B.
Neither result establishes that AVIC, NPT, host broadcast flushes or hardware are healthy.

## Diagnostic canary and next discriminator

`tools/guest-tlb-canary.c` alternates two known 8 MiB file backings at one virtual
address. Eight synchronized readers check the first 64-bit word of every 4 KiB page
only after each completed remap. It reports remaps, page checks and mismatches as
JSON; mismatch exits 1, setup failure exits 2. Build and run in the macOS guest:

```sh
xcrun clang -std=c11 -O2 -Wall -Wextra -Werror -pthread tools/guest-tlb-canary.c -o /var/tmp/rgpu-tlb-canary
/var/tmp/rgpu-tlb-canary 30
```

A mismatch would be useful evidence. Passing this narrow workload does not establish
memory correctness: APFS errors and image disagreement occurred in guests that passed it.
The compatibility SHA rejection remains mandatory; its error now includes the affected
image and both hashes to distinguish corruption from generic agent failure.

The single-vCPU software-emulation comparison ended without a command response;
it did not obtain a qualifying control. The fresh control already reproduced
image disagreement with PCIDE clear, so the extra PCID-off trial was cancelled.
The instrumented transfer comparison and host-cache/IH investigation above
supersede another CPU-feature A/B as the next priority. Fresh GPU-less trials
after the bounded IH stop test the contained state, without re-enabling GPU
DMA. Production files and the earlier trial clone remain untouched. The
permanent fix must stop IH/ring writeback **before guest-memory mappings are
released**, then include IH quiescence in normal/no-queue recovery and launch
proofs. A cleanup after QEMU has exited alone leaves an exposure window.
Crash, forced-stop and native-shutdown paths need separate qualification. A
physical-page/translation match remains a useful discriminator. Upload
disagreement must remain separate from the earlier APFS/panic evidence unless
their common cause is actually demonstrated.
No general KVM, CPU/host translation or guest/OpenCore qualification follows;
the concrete orphan-IH exposure takes priority over another speculative CPU
variation. A per-VM AVIC comparison was not obtained. Changing host
`kvm_amd` AVIC/NPT parameters or selecting another host kernel needs the user's explicit
instruction because the handoff requires the host configuration to remain unchanged.
Do not promote kernel-update timing or a clean short boot to a root-cause/fix verdict.

The production config and both boot images were restored byte-for-byte before clone
trials; `production-configuration-restored.json` records their hashes. Desktop selection
remains release 514 / metal-318 / QEMU pins v18. Diagnostic guests had no VFIO
attachment. The separate IH containment above changed only its documented
register enables. No GPU reset, binding change, host KVM parameter change,
extra guest kext or Apple-account operation occurred.

Host suite: 1637 tests passed, 8 skipped. Hosted test/build for baseline 319a2dd passed.
The continuation reran the full host suite successfully (same 1637 tests / 8
skipped; `continuation-01/host-suite.log`). No new commit, push or hosted CI
result was produced. Final read-only sampling (`igpu-ih-readonly-02.json`)
confirmed control `0x1031001e`, ring/writeback disabled and WPTR stationary at
`0x1` after both fresh guests exited. KVM parameters, vfio-pci binding,
power/control=on and the host boot were preserved.

## Candidate 515 repair qualification (after the investigation above)

The earlier no-commit/no-GPU-exposure state describes the investigation, ending
before this repair phase. Implementation and bounded GPU qualification are now
authorized. Audio remains deferred; bindings and host KVM settings are unchanged.
See `docs/ih-dma-lifetime.md` for the source/lifetime contracts.

- Installed Tahoe GPU-less refresh `153a345852004dd0b6449bd277be1960` passed all
  four guest/upload image hashes and sealed native exit 0 after IH containment.
  Identity and output are in `continuation-01/tahoe-after-ih-stop-*`.
- Original desktop 514's intact schema-6 receipt was requalified through fresh
  MODE2, IH shutdown and complete queue/host scans. The separate schema-9
  receipt is `continuation-01/ih-requalification-before515-02.json`; the original
  canonical and run receipts were not rewritten. Its first attempt refused
  before opening VFIO because the old tool admitted only failed recoveries;
  the added upgrade path validates the complete original canonical proof.
- Native GPU run `083451d7ee2a8bc3b39b508dc8dc4d12`, build
  `90c57452e22f449ca010e6d08cf51f83`, QEMU image
  `308e792c19fa11ef0e4850e1023e5155b4ae8579b0e1ea50029f54346d76a975`:
  `CORE_PROBE_PASS`, readable GTK desktop capture, native requested shutdown
  with direct natural exit 0. Guard trigger `qemu-stopped-exit-hook`:
  IH0 `0x1033011f` / WPTR 126528 -> `0x1031001e` / stable WPTR 0, before DMA
  unmap. Full recovery schema 10 recovered / authorizes_launch=true.
  Results: `~/macos-vm/run/candidate-515-results/`; window PNG:
  `continuation-01/c515-native-01-host-window.png` (kept local).
  HMP screendump returned `no surface` for the GL console; it is not a successful
  capture. The separate host-window image establishes the visible result.
- Full preflight suite: 1650 tests passed, 8 skipped. Abrupt death/relaunch,
  longer soak and post-GPU fresh-clone integrity checks remain pending.

- Abrupt test `9fc73c08a7081e1b9d72193f612610a3`: nonce-bound Metal probe
  passed before `signal.pidfd_send_signal(SIGKILL)` targeted the verified QEMU.
  It was also container PID1. An HMP pause (which drains/flushes all block
  devices) allowed a fresh disk reflink before resume/injection. The coordinator
  and separate guard were not signaled. Guard trigger `qemu-death` stopped IH0
  `0x1033011f` / WPTR 89728 -> `0x1031001e` / stable WPTR 0; SDMA RLC0 RB/IB
  enables were cleared. Full schema-10 recovery recovered / authorizes_launch=true.
  The overall wrapper is INVALID (`docker inspect failed` after intentional
  process death), shutdown already-stopped; neither is native shutdown proof.
  Evidence: `candidate-515-attempt-procdeath01-results/` and
  `continuation-01/c515-procdeath-01-injection.json`. The intervening Tahoe
  GPU-less refresh passed four image hashes/native seal after the first GPU run.


### Post-crash plain guest failure (qualification blocker)

GPU-less refresh nonce `5e88f1b2865a4253839f8969dde20adb` matched all four
images but did not exit. Read-only HMP capture found seven CPUs parked in the
MP rendezvous and CPU 3 in panic stackshot code. The live BootKC contains a
unique 96-byte match to the runtime instruction sequence, establishing fileset
slide `0x19600000` (independently corroborated by the panic header).

The first panic at 71.997078355 s uptime was a NULL dereference in
`phys_attribute_test+0xce`, called by `vm_map_page_range_info_internal` /
`mach_vm_page_range_query` for process `heap`, after shutdown began. Its physical
page reverse list links to `0xffffff962f596300`; 512 bytes at that pmap address
were zero. The preceding `pmap_pte` call returns NULL when `pm_pml4` is zero;
the next instruction dereferences it. This establishes an inconsistent guest
reverse mapping, not its cause. A nested panic has malformed text; no IH-record
signature has yet been established in this guest capture.

Evidence under `continuation-01`: `aftercrash-panic-buffer.txt`,
`aftercrash-plain-symbolication01.json`, `aftercrash-fault-context01.json`,
`aftercrash-fault-loop01.txt`, `aftercrash-pmap-context01.json`. The full 12 GiB
`aftercrash-plain-guest.core` was dumped with QEMU paused (`info dump: completed`).
Only this owned GPU-less CID `01929eaf7c1d` was then stopped through its original
bounded user unit `rgpu-compat-plain-5d33904a94c6`. This is forced diagnostic
shutdown, not native proof. No GPU exposure/ledger entry for `aftercrash01`.
The passing guard/recovery receipts do not clear this new failure or establish
whole-guest stability. Audio is authorized only after memory qualification passes.


**Follow-up distinction.** Fresh original macOS 15 rollback control
`control-03-after-procdeath` passed canary, all four hashes and native exit 0
in 103.9 s after this guarded GPU crash. It used only `/dev/kvm`, eight CPUs,
8 GiB, NVMe and Lilu/plugin off. IH read-only samples at 08:41 UTC show control
`0x1031001e`, WPTR 0 stationary (`igpu-ih-readonly-after-procdeath.json`).

Full Tahoe RAM scan found two 256-record IH sequences. Both exactly occur in
the production qcow2 file at `0x17aa04000` and `0x17aa06000`. Buffered and
O_DIRECT 64 KiB reads agree there, as do both immediate/pre-investigation backups.
Both sequences also occur in the 2026-10-14 21:35 backup, before repair testing.
These are persisted historical disk bytes; their presence in the new guest
alone is not evidence that the repaired IH ring wrote again. Current BootKC and
SystemKC have no three-consecutive-record match to this marker. The file owner
and relation to the new panic remain unresolved. Evidence:
`aftercrash-core-ih-signature-scan.json`,
`aftercrash-ih-disk-direct-and-backups.json`,
`aftercrash-ih-earlier-backup-matches.json`, `aftercrash-ih-disk-map.json`.
A raw conversion is being made for read-only APFS inspection; the production
image and backups are not being repaired or replaced.


### Focused pmap control and broader teardown boundary

`tahoe-pmap-01` reflinked the unmodified production disk and copied its exact
OpenCore/config into an isolated GPU-less VM (stock QEMU, 12 GB, eight CPUs,
AHCI; no VFIO/DRI/TAP). It passed 47,495 remaps / 97,269,760 page checks,
120 s of `tools/guest-pmap-lifetime-stress.c` (105,251 self page-range queries,
154,842 fork/exit children sharing clean file pages), four image hashes, and
native exit 0. This is a scoped control, not an explanation of the earlier
`heap` panic. The new probe exercises the same public query API while other
pmaps for shared pages appear/disappear; instruction-level execution coverage
has not been traced.

The raw-disk IH signature scan found three clusters (1,064 records). Two active
extents belong to Data inode 2845334, `/System/Library/Caches/com.apple.coresymbolicationd/data`;
the third is a duplicate without an owner in the current filesystem trees.
This signature-specific scan is not a complete filesystem integrity check.
The read-only inspector was built locally from `sgan81/apfs-fuse`, with only a
missing `<cstdint>` include added for GCC 16; DeviceLinux opens O_RDONLY. Its
source, logs, isolated raw conversion, extent mappings and scan results remain
under `continuation-01`. No production cache deletion/repair has occurred.

A separate teardown audit found schema-1 guard does not halt GC or all SDMA
inputs before releasing mappings. The SIGKILL run's later recovery saw
CP_ME_CNTL 0, five active HQDs, SDMA F32 unhalted and GFX/PAGE inputs enabled
(SDMA status did report idle). These observations do not prove a DMA write or
attribute the later panic. They establish that the guard's release boundary
needs stronger engine proof. New schema-2 guard uses `tools/dma_engines.py` to
close measured inputs, halt CP/SDMA and require timed CP/CPC/GRBM/SDMA idle
samples before SAFE/release. It preserves other register fields and does not
retire queues/reset/rebind. Full recovery remains separate. Offsets/masks match
the sealed recovery and Linux gfx_v10_0 / sdma_v5_2 source at the audited ref.
The native schema-2 run `0e6dd8a6bb200cc3a4d84e0c6498305f` passed the
desktop Metal probe with zero sampled mismatches, retained capture and exited
after the guest shutdown request. The guard released only after five samples
showed IH stationary plus stopped/idle GC and SDMA. Ordinary recovery then
returned incomplete: all 16 active HQDs timed out during dequeue, host KIQ
reported blocked-active-hqd and CPC_BUSY was nonzero. This is a consequence
of halting GC before the existing post-unmap retirement sequence; it is not a
new corruption observation. Evidence: `run/candidate-515-attempt-enginehalt01-results/`.

Read-only no-queue inspection correctly rejected the active HQDs. The separate
stopped-device path then performed MODE2 and two complete inactive scans,
stopped IH again, confirmed PSP teardown and produced a schema-9
`authorizes_launch=true` receipt. The original incomplete receipt is intact.
Evidence: `continuation-01/enginehalt01-noqueue-inspection.json` and
`enginehalt01-noqueue-recovery.json`. The wrapper now attempts this strict
fallback after a released schema-2 guard and incomplete ordinary recovery;
the next run below validates the native automatic path.

The next native run `d53a27bbd753a6becaae13c6e40a81e8` passed the same
Metal readback probe, preserved serial/critical capture and exited after the
guest request. Schema-2 guard released with stopped/idle proof; ordinary
recovery again found halted active HQDs and was incomplete. The supervised
wrapper then ran the stopped-device MODE2/no-queue path automatically; its
separate schema-9 receipt is recovered/authorizes_launch=true and the wrapper
exited 0. The preceding plain Tahoe compatibility refresh matched all image
hashes and exited natively. Abrupt-stop and post-crash integrity remain open.

Read-only APFS FUSE mounted the converted disk and read the 1,700,233,216-byte
symbolication cache. Its SHA-256 is
`250094bc989f5b2592dfbf4c6d3df2f22bb4a08fad0e376172e0db0d8330ce4c`.
At file offsets 430,931,968 and 467,639,040 the first word is the IH header
`0x80005704`; the 4 KiB samples contain respectively 128 and 40 such headers.
The exact file sample and hashes are in
`continuation-01/tahoe-corrupt-symbolication-cache.json`. This confirms the
extent attribution; the cache has not been repaired and no causal connection
to the later pmap panic has been established. Abrupt GPU requalification and
post-crash integrity checks remain pending.

### Second abrupt death and post-crash guest integrity

Run `c60f611464eade014bfa16d65097c0e0` passed its desktop Metal readback
before an identity-checked pidfd SIGKILL of QEMU/container PID1. A paused,
flushed disk reflink was saved first. The independent guard survived, recorded
`qemu-death`, then released after five IH-stationary and GC/SDMA stopped/idle
samples. Ordinary recovery was incomplete as expected with halted active
HQDs; the supervised MODE2/no-queue fallback produced a separate schema-9
`authorizes_launch=true` receipt. Wrapper INVALID (`docker inspect` after
process death) and already-stopped shutdown describe the injected crash, not
Metal output or native shutdown. Evidence:
`run/candidate-515-attempt-procdeath02-results/` and
`continuation-01/c515-procdeath-02-injection.json`.

The installed plain Tahoe guest then passed all four image hashes and native
exit 0 (nonce `2f2c09e5228241d0b269789eab3cd039`). A bounded repeat with
the remap canary and page-query/fork probe passed 44,291 remaps/90,707,968
page checks and 104,919 queries/150,415 children over 120 s, then four image
hashes and native exit 0 (nonce `0bb1db7e8c10458693fec4ad8f58453c`).
These observations do not establish the cause of the earlier pmap panic.

The Data cache file changed size during normal guest operation, from
1,700,233,216 to 1,704,050,688 bytes, but its two mapped offsets still began
with the exact IH record bytes. A fresh stopped-disk reflink backup was saved
as `backups/mac_hdd_ng-before-cache-quarantine-20261015.qcow2`. In an isolated
Tahoe clone, the 1,700,233,216-byte file matched the prior SHA-256, was renamed
to `data.rgpu-corrupt-20261015`, and remained there after reboot while the
original path was absent. The clone then passed 107,612 page queries/152,192
children, four image hashes and native exit 0 (nonce
`6dd02432767b442c8f4076031c2eef7e`). The installed guest's cache was
renamed the same way after checking both signatures; it preserved a
1,704,050,688-byte quarantine file and sealed native shutdown. Its rebooted
stress passed 42,771 remaps/87,595,008 page checks, 102,387 queries/147,028
children, four hashes and native exit 0 (nonce
`b3a48bb4e0224d1aa273de12f92f3a84`). The rename repairs the known bad
cache path without proving that cache caused the pmap panic. Repeated lifecycle
and integrity checks remain necessary before a stable release claim.

A repeat exact QEMU/container PID1 SIGKILL on the repaired installed disk,
run `911cda8adc60b63a8c031be608f1cba9`, passed Metal before the signal.
The guard again released on `qemu-death` after five stopped/idle samples; its
automatic MODE2/no-queue fallback again authorized reuse. The paused/flushed
disk backup, identity-bound injection and receipts are under `continuation-01`
and `run/candidate-515-attempt-procdeath03-results/`. A fresh plain Tahoe boot
then passed 44,701 remaps/91,547,648 page checks, 108,618 pmap queries/152,410
children, all four image hashes and native exit 0 (nonce
`1745e1076ed34218bb0b55c84f910c3f`). These are two bounded crash and
post-crash integrity sequences. They support the repaired teardown boundary
and known-cache cleanup, while leaving the exact earlier pmap panic cause and
unmeasured autonomous DMA sources unresolved.

### Installed desktop path and final plain control

The installed release-515 launcher (`metal-321`, QEMU pins v19) ran attempt
`d20261015133753` / cycle `92e438ba58725f977267dbd21b381319`.
Metal readbacks passed and a local GTK capture showed a readable Tahoe desktop.
The normal launcher stop produced a guest-requested native QEMU exit, schema-2
guard release with measured stationary/idle proof and separate automatic
MODE2/no-queue schema-9 recovery with `authorizes_launch=true`. Wrapper
CORE_PROBE_PASS and return code 0. The private window capture is retained only
locally at `continuation-01/product515-window-local.png`. The preceding desktop
attempt `d20261015133701` failed shell argument parsing before cycle/QEMU/VFIO
opened; it consumed no GPU ledger entry. The launcher quoting was fixed before
the successful run.

After that product session, direct GPU-less Tahoe refresh sealed nonce
`7390f2a8808c407d8b0886cc7fcafc6f`: all four guest/upload image hashes
matched and native shutdown exited 0. The measured DMA boundary and repeated
bounded integrity checks support this release on the recorded host boot. They
do not establish the exact cause of the earlier pmap panic, clear KVM, prove
every autonomous device engine inactive, or establish long-term stability.
