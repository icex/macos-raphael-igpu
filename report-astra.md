# Astra review after candidate 186

2026-09-10. Offline, read-only review; only this report was written. No VM,
device access, sudo, reset, rebind, implementation edit, or hardware test occurred.
Reviewed current `status.md`, frozen 183/186 evidence, production sources,
relevant tests, the prior review, and exact cached 24G830 binaries.

**Finding: the no-generic-display transition changed the guest GPU PCI address,
but OpenCore still injects its required properties at the old address.**
Candidate 186 reaches driver callbacks, then rejects the Raphael target identity
before acquiring its recovery lease. The subsequent KIQ refusal is correct.
The WindowServer panic is a downstream consequence of the uninitialized VMM
paging channel. This is a startup regression, preceding 183's VMID1 faults.

## Evidence and failure chain

Paths below are relative to the repository unless otherwise stated. `186 serial`
means `findings/experiments/metal-019-186/raw/run-output/serial.txt`; `183 serial`
means `findings/experiments/metal-016-183/raw/serial.txt`.

| Boundary | Candidate 183 | Candidate 186 |
|---|---|---|
| Guest GPU identity | AMD messages identify `[0:6:0]` | `[0:5:0]`, including explicit `DeviceID` at serial:1993 |
| Raphael VMM gate | `marked=1 aperture=1 mode=4`, serial:2396 | `marked=0 aperture=1 mode=4`, serial:1892 |
| SDMA topology | Startup proceeds with repaired topology | Explicit target rejection, serial:1899–1901 |
| Lease/VMM reservation | OWNED; VMM base `0xf40b6f3000`, serial:2532–2533 | `lease-owned=0`, base zero, serial:1967 |
| KIQ/engines | Native KIQ returns 0; HW engines return 1 | KIQ refused; PM4/HW engines return 0, serial:1984–1988 |
| Execution | Later VMID1 translation faults | NULL paging-channel panic before valid probe |

The frozen 186 `staged-config.plist:352` places all three GPU properties under
`PciRoot(0x0)/Pci(0x6,0x0)`: a 46,592-byte `ATY,bin_image`,
`rgpu,raphael-target = RGPU-RAPHAEL\x01`, and `PP_PhmUseDummyBackEnd`.
Its frozen `running-identity.json` records:

```text
vfio-pci,host=0000:7b:00.0,bus=pcie.0,x-pci-vendor-id=0x1002,x-pci-device-id=0x73ff,romfile=/run/vm/gpu.rom
```

There is **no explicit guest `addr`**. `tools/macos-vm.sh:211` constructs that
command; `tools/vm-entry.sh:59` removes the generic VGA device. The observed
slot change and unchanged injection path explain why source-preserving headless
startup loses its device identity. The correct host BDF and spoofed PCI ID do
not deliver OpenCore properties to the matching guest device. A QEMU ROM file
also does not establish that the IORegistry marker reached that device.

`src/RaphaelGPU.cpp:4666` requires original GC discovery, vendor/device IDs,
`ATY,bin_image`, and the exact marker. GC 10.3.6 was already observed at 186
serial:1446, and the framebuffer aperture is published. Nevertheless, both the
VMM gate and topology wrapper reject the target. At `wrapVmmSetVSReady:4354`,
that same identity check is an ownership prerequisite. On failed preflight,
`src/RecoveryLease.hpp:410` invalidates the lease and returns without calling
the native VMM reservation. Consequently there is no initialized VMM base,
no forced paging-channel enable, and no OWNED publication. No live-GART
validation message precedes this failure. Changing COM2 capture cannot repair
that native state.

This causal diagnosis is strongly supported; the capture does not contain a
per-property IORegistry dump proving exactly which required property was absent.
Do not describe a directly inspected missing marker. The topology/path mismatch
itself is demonstrated, and target rejection is directly observed. The relevant
identity/lease wrappers have no changes between the 183 and 186 commits.

I recomputed all three cached KDK hashes and UUIDs: they match both manifests
and `findings/baseline-identities.json`. The guest panic's X6000 UUID is also
`72574DE5-9646-3F51-AC2E-ADF626B4093B`. Fresh disassembly of that exact binary
confirms `setVirtualSpaceReady` writes the reservation base at `x6+0x57915`,
and `endVMPTUpdate` loads `[this+0x28]` at `x6+0x589f9`, then dereferences it
at `x6+0x589fd`. The latter equals the observed panic PC relative to the loaded
X6000 base; RDI and CR2 are zero. This supports the downstream failure chain.
The earlier `setMemoryAllocationsEnabled(0)` NULL warning also appears in 183,
so that warning alone is not a regression.

## Why the methodology missed this

1. **Identity checks were internally consistent but incomplete.**
   `tools/experiment.py:204` verifies the marker at a hard-coded slot 6;
   `validate_running:2180` verifies host VFIO identity and graphics/serial options,
   without binding guest PCI address to the OpenCore path. Both pass the broken
   186 combination. Their current marker test explicitly accepts slot 6 without
   a launch topology argument (`tests/test_experiment.py:945`).
2. **The headless test removed graphics without testing its PCI consequence.**
   `tests/test_vm_entry.py` checks a minimal fake launcher and forbidden display
   arguments. The no-GPU macOS qualification usefully proved Lilu dispatch, but
   could not prove delivery of properties to an absent Raphael endpoint.
3. **Recovery tests cover the lease protocol better than its deployment inputs.**
   The actual helper preserves append/publication/native ordering and fails
   closed. Source tests assert this ordering, but never compose the guest PCI
   placement, OpenCore property path, target predicate, and lease preflight.
   More full-suite passes would not cover that missing integration contract.
4. **Readiness must be reported by boundary.** Routes and complete snapshots are
   successful observations. `marked=0`, topology rejection, and KIQ refusal are
   earlier functional failures than the final missing-record classification.
   The corrected current status is accurate about engine failure; retain that
   correction in future handoffs. The 183 VMID1 investigation remains relevant
   only after startup is restored.

## Revised hypothesis and one discriminating next test

**Hypothesis:** binding the VFIO endpoint to the guest PCI address named by the
existing OpenCore property path restores target identification, ownership, and
native startup under headless Lilu, without modifying VMID1 translation behavior.

Prefer an explicit, reviewed `bus=pcie.0,addr=0x6` contract matching the existing
slot-6 properties, after checking the full generated machine for collisions.
Moving properties to another automatically assigned slot leaves the same defect
available for the next topology change. Do not relax the marker or lease guards,
force an OWNED state, forge a receipt, or NULL-stub the panic.

Before another GPU cycle, implementation and coordinator should:

- Add a production-path contract test that rejects the frozen 186 combination
  (unbound guest address plus fixed property path), accepts the explicitly matched
  address, and rejects wrong bus/function, duplicate/conflicting assignments,
  missing properties, and graphics-mode changes that break the relationship.
  Exercise the actual generated launcher with a harmless command capture;
  verify complete PCI placement separately with a no-VFIO topology fixture if
  needed. A fixture is not evidence of real guest property delivery.
- Preserve a bounded target-check diagnostic containing the guest location and
  pass/fail facts for GC discovery, vendor/device, ROM-property size, and marker.
  Capture the lease preflight rejection stage, without adding MMIO or waits to
  locked callbacks. This distinguishes delivery failure from another owner or
  native-reservation failure in one observation.
- Replay the 186 startup observations through readiness checks: target rejection
  must never admit a probe or authorize recovery, despite complete route/capture
  evidence. Preserve existing finite deadlines and receipt restrictions.

Only after those checks, report assessment, and normal fresh authorization may
one GPU run test the hypothesis. Required ordered evidence is: correct guest
location/properties; `marked=1`; topology applied; OWNED with nonzero native VMM
base; paging channel present; native KIQ success; engine startup; ACTIVE pool
and VALID lifetime. A recurrence before any boundary falsifies the corresponding
hypothesis and stops functional interpretation. If startup is restored, retain
the existing bounded VMID1 diagnostics and unchanged desktop/Metal probe, then
perform the ordinary independently validated cleanup. Restored startup alone
is not functional acceleration or a reason to reset the broader unresolved count.

## Evidence integrity and authorization

Reviewed run: `8ec4b0197975c1df32f408f188de64ce`, boot
`81e1e41f-f11b-40d0-b202-20850c245ead`. The unresolved count remains eight actual
GPU cycles, four since the post182 review: 183, GUI-183, 185, 186. The current
run has no recovery receipt; spare ledger capacity does not authorize reuse.
This report grants no safety-gate bypass. No Claude review was performed here.

Recomputed frozen SHA-256 values:

```text
serial.txt   1bb600905f78139a8868a06c08838ea3f8964cb09503ab0bc19aa925bfccd2b7
critical.txt 210e1c2b573da997a541a0ca892b202251e668a1a5a02378585c3033dd9e084c
prior report 98a247bacc8f2d2e0db4d8e7bc3164a57f19df3dc0a6901488d54548df0f3037
```

The prior report is preserved at
`findings/research/astra-reviews/2026-09-10-post186-180456/report-astra-before186.md`.
The critical digest in the initial refreshed status omitted `1a`; the coordinator
was notified. No frozen evidence was changed. Existing suites were inspected,
not rerun during this read-only review.
