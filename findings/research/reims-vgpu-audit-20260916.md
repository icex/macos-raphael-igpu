# Reims vGPU source audit — 2026-09-16

**Result:** useful independent test designs and memory-ownership lessons, but no
replacement for Raphael's AMD driver, physical-display work, reset procedure or
OpenCore/SMC portability work. No code from Reims was incorporated. All suggested
Raphael changes below are unimplemented hypotheses or qualification work, not
validated fixes.

## Identity and coverage

Cloned `https://github.com/steelbrain/reims-vgpu` into
`/home/bogdan/macos-vm/run/research/reims-vgpu-20260916` at
`69a57dd69a6958e946c03b73e02db331f330f435`, committed
2026-09-03T23:29:26+03:00. Initialized its QEMU submodule at the recorded
`bd88218da09b86ed9c78bf5f9354168812a7ba6b`. The host Cargo manifest pins
`metal2vulkan` to `9e0e99a41dc3cb8bb7e288b531f1698a79fd4b1c`; that separate
translator was not cloned or audited. Exact file hashes and the Raphael comparison
commit are in [the evidence inventory](reims-vgpu-audit-evidence-20260916.json).

Surveyed the major components: device/QEMU ABI, wire decoding and oracle,
backend-neutral scheduling, Vulkan/Metal execution, guest memory and resource
lifetimes, display/EFI, event synchronization, recovery, configuration/build,
VM launch scripts, visual probes and conformance cases. Selected implementation
paths were read in depth; this is **not** an exhaustive line-by-line correctness
or security audit of 481 crate files or the whole upstream QEMU tree. No external
build, test suite, installer, guest command or GPU operation was run. Upstream
comments and committed baseline results describe upstream observations, not
results reproduced on Raphael.

References below are paths and starting line numbers in those pinned trees;
[the pinned upstream tree](https://github.com/steelbrain/reims-vgpu/tree/69a57dd69a6958e946c03b73e02db331f330f435)
keeps them reviewable. Local source is also available in the clone above.

## Architecture and applicability

| Component | Source evidence | Consequence for Raphael |
|---|---|---|
| Guest interface | `README.md:14`; `crates/reims-vgpu/src/qemu/host_ops.rs:36`; QEMU `hw/display/reims-vgpu-pci.c:1` | Emulates a device consumed by Apple's existing **AppleParavirtGPU**, with host Rust execution behind QEMU C callbacks. Raphael instead exposes physical AMD PCI hardware and adapts the native AMD stack. This is an alternative architecture, not a compatible driver component. |
| Host rendering | `crates/reims-vgpu/Cargo.toml:17`; `src/backend/vulkan/caps/device_features.rs:1`; `src/runtime/draw/metal/depth_stencil.rs:1` within that crate | Vulkan translation and direct Metal implementations exist. The README's “Metal (TODO)” wording is not a sufficient source inventory. Neither backend contains a Raphael DCN/VCN hardware implementation. |
| Display/firmware | `crates/reims-vgpu-efi/README.md:1`; `src/runtime/scanout/mod.rs:128` | The GOP belongs to virtual PCI 106b:eeee and its own linear BAR1. Scanout retains a finished host image before completion publication. It does not establish AMD HPD/AUX/PHY/link training, boot-parser topology or physical display. |
| Codec | Full crate filename/text survey; `src/runtime/gva_mem.rs` and related names | Here GVA means **guest virtual address**, not Apple's codec framework. No H.264/HEVC implementation or native AppleGVA resolver repair was identified. Our Main10/explicit-ID limitations remain separate. |
| Hypervisor dependency | `.gitmodules:1`; `vendor/qemu-patches/README.md:1`; QEMU product shims | Requires custom QEMU device integration and host callbacks. HostOps is a possible porting boundary, but there is no VirtualBox implementation in this tree. This does not remove our patched-QEMU dependency. |
| SMC | QEMU `hw/misc/applesmc.c:58`, `:128`, `:168`, `:210` | Declares command 0x12 but its command/data handlers implement only READ_CMD. No substitute for our key-index enumeration fix was found. Keep pursuing guest/OpenCore ownership separately. |

The project is explicitly alpha. Committed macOS-15 conformance debt includes
buffer-storage aliases, retained depth, non-divisible dispatch grids, array
views and indexed draw variants (`conformance/expectations/macos-15/driver-errors.txt:1`).
Those are upstream reported limitations, not proof that Raphael has them.

## Concrete opportunities, ranked

### 1. Make extended visual checks compare intended content with delivered pixels

Reims' web probe records its own palette and screen rectangles, then checks host
captures there (`scripts/web-content-probe/web-content-probe.sh:5`, `:256`, `:272`).
Its visual gate combines web content, wallpaper and modal controls, with separate
setup failure and rendering failure (`scripts/visual-gate/README.md:1`). This is a
stronger extended-desktop instrument than an animation count plus a few images.

Our `tests/desktop_composition_page.html` currently drives blur/transforms, while
`tests/desktop_material_endurance_probe.m` and the raw RFB captures establish
bounded composition evidence. Extend these with independently generated expected
regions and changing frame tokens. Use native raw RFB output, because our known
feedback defect could leave a native screenshot clean while remote pixels were
wrong. Synchronize capture to a visible token and account for resize, scale,
occlusion and color transfer before scoring. Keep animation callbacks separate
from actually observed presentation.

**Discriminator:** after a stable token, the remote pixels in each declared
region match its palette/pattern, including a second frame whose untouched areas
must retain prior content. Deliberately shifted regions and a stale captured
frame must fail the *instrument's* host-only checks. Run the instrument on the
known-good current build before treating a later difference as a regression.
Do not import Reims' nonzero dropped-write budgets: its documented admitted
losses are not our qualification policy.

### 2. Test mixed CPU/GPU writes and retained LOAD, not just complete replacements

`src/runtime/resource_validity.rs:18` explains how delayed host writes can
clobber a newer guest write; `src/runtime/writeback_debt.rs:1` distinguishes
resource visibility from completion stamps. `src/runtime/surface_currency.rs:63`
and `:93` distinguish observed dirty pixels, writes outside the pixel window,
and missing tracking evidence. These are software-emulation mechanisms, not an
AMD DCC patch to transplant.

The transferable test is `conformance/suite/cases/SampledAlias.swift:280`:
GPU paints one half, CPU updates the other after completion, and an optional
LOAD pass changes only the first half. Both halves must survive. Our
`src/TextureDiagParser.hpp:75` repairs one exact native feedback instruction;
`tests/texture_reclamation_probe.m:37` and the feedback/XPC tests do not by
themselves establish every CPU/GPU ownership transition.

**Discriminator:** independently seed each half/round, use supported managed or
IOSurface storage with the required CPU/GPU synchronization, render with LOAD,
then check every active pixel and row-padding sentinel. Compare no-second-pass,
LOAD-second-pass and fresh-resource controls. A failure should first be localized
to storage/transition/representation before changing cache or DCC behavior.

### 3. Broaden plane, view and retained depth coverage

- `conformance/suite/cases/BiplanarSurface.swift:17` creates separately pitched
  R8 luma and RG8 chroma planes with distinct coordinate-derived values. Extend
  our IOSurface tests beyond BGRA plane 0, preferably through public CoreVideo
  allocation and per-plane Metal imports. This is different from the already
  passing full-plane Main10 **codec** comparison. The discriminator is correct
  geometry, offset and content for both sampled planes, including padding and
  plane-specific CPU updates. Adapt storage mode to the actual AMD device;
  upstream's `.shared` assumptions are not portable without checking.
- `conformance/suite/cases/TextureView.swift:108` targets array-slice identity;
  `SampledAlias.swift:381` targets nonzero buffer offsets. Add mip/slice/view
  tests with distinct values, dimensions and independently computed pitch.
  Changing one subresource must leave the others intact.
- `conformance/suite/cases/DepthStencil.swift:41`, `:232`, `:308` address depth
  aspect copies, task isolation and retained state. Our
  `tests/depth_stencil_probe.m:199` covers bounded depth/stencil transitions and
  1×/4× color resolve, not retained cross-pass depth. Next small test: pass A
  writes depth/stencil, pass B LOADs and uses comparison to produce a CPU-known
  color mask; repeat across formats and independently seeded processes. Keep
  depth resolve and stencil-aspect copy as separate cases.

### 4. Separate alias reuse from page-table release

`src/backend/vulkan/engine/resource_lease.rs:29` includes mapping generation in
resource identity; `src/runtime/mapper/mod.rs:1000` revalidates physical page
lists; `src/runtime/released_pages.rs:1` documents a write-after-release detector
and its important remaining false-positive case when another task still maps the
same page. This supports the distinction already recorded in our roadmap:
reused GPU addresses do not prove page-table teardown.

`conformance/suite/cases/HeapTextureAlias.swift:29` offers a bounded automatic-heap
lifetime test: exhaust one slot, finish work, make the resource aliasable, reuse
the same offset, then verify new content. Implement a fresh native probe rather
than transplanting the emulator's page tracker. Our
`src/VmEntryUpdate.hpp:68` already preserves invalid/unmap templates and separates
system memory; retain those guards.

**Discriminator:** new allocation/alias content is correct with old content
chosen to fail conspicuously; correlate actual native unmap/invalidate operations
and final backing counters for any page-release claim. Never classify a write as
use-after-free without proving no other live task/view owns that backing.

### 5. Extend ordering tests only where they add coverage

Reims' `crates/reims-vgpu-core/tests/progress_is_always_possible.rs:1` explores
adverse schedules and separates producer submission from producer completion.
`src/runtime/parked.rs:48` binds retained work to device epoch so an old completion
cannot masquerade as work from a recreated device. These are useful invariants.
Its `src/runtime/fence_exec.rs:1` is not the entire scheduling model; reading the
soft-pending helper alone would mischaracterize scheduling. Timed event records
are explicitly refused at `src/runtime/exec/mod.rs:1853`.

Our `tests/iosurface_xpc_event_probe.m:2` already commits the consumer first and
checks a shared surface across processes, stronger evidence than merely copying
Reims' 64-byte cross-queue test. Remaining useful cases are multiple independent
producers, monotonically increasing event values, unrelated work making progress,
and helper termination with completed versus pending work clearly separated.
Bound every wait and retain the existing shutdown/recovery route. No native AMD
queue scheduler rewrite is supported by this audit.

## Safety, observability, build and test lessons

QEMU `hw/display/reims-vgpu-pci.c:928` joins heartbeat/drain workers, closes the
host window and destroys the backend before host driver unload. This is relevant
as an ownership-ordering example, **not** a VFIO recovery proof: our physical
queues survive process closure and still need independent MODE2/recovery receipts.
`vm/boot-x86.sh:789` uses TERM/KILL for bounded virtual-device boots. Do not replace
our cycle supervisor with that launcher or call those exits clean shutdowns.

`src/backend/vulkan/engine/device_lost.rs:69` latches a device loss even when no
future draws arrive. `src/runtime/compute_exec/stall_watchdog.rs:32` uses a bounded
16-slot watch registry and reports inability to watch. Both reinforce retaining
independent deadlines and explicit observation gaps; no concrete missing Raphael
watchdog was demonstrated. Existing critical capture limits/abort paths remain.

The wire oracle derives serializer bytes independently of parser constants
(`crates/reims-vgpu-wire/README.md`, `build.rs:1`). Missing fixtures are ignored or
made required, not silently passed. Its selector manifest explicitly warns that
inherited selectors are missing from the direct-class inventory
(`src/manifest.rs:1`): a method absent from one class list is not proof it cannot
be called. Apply that caution to provided AMD decompilation and verify ABI with
disassembly/vtables, as our current work already does. AppleParavirt's wire
opcodes/layouts themselves do not describe AMD PM4 or DCN registers.

`conformance/README.md:18` distinguishes native correctness, candidate/control
regression, missing cases, fixed known failures and native-oracle failures.
`conformance/ratchet.py` and the README distinguish repeated controls from noisy
one-off counts. Useful improvement: give every added case a stable semantic ID
and require its result; do not encode device-specific row pitch in the ID. Keep
actual geometry/alignment in details. Do not adopt a failure inventory without
first establishing the same case's contract on our exact macOS/AMD path.

`scripts/feature-matrix/feature-matrix.sh:1` checks all build-feature targets,
including an EFI workspace separate from host code. Our corresponding delivery
need is explicit setup/config validation and a tested hypervisor/SMC-provider
matrix, not an imported Rust build system. Reims' snapshot-per-OS scheme is useful
for reproducibility but cannot replace physical-GPU boot/reset identity.

## Provenance and reuse constraints

The root README and LICENSE identify LGPL-3.0-or-later, while **all ten host
Cargo manifests identify GPL-2.0-or-later**. QEMU product shim SPDX headers also
say GPL-2.0-or-later. This metadata conflict is unresolved here; do not describe
the whole checkout as uniformly licensed or copy files into our driver on that
assumption. No legal compatibility conclusion is made. Record exact origin and
resolve applicable terms before any source reuse. Independently written public
Metal-API tests can be designed from the behavior described above without copying
upstream implementation text.

The wire oracle uses an Apple framework version distinct from our 24G830 native
AMD corpus, and generated Apple serializer fixtures are intentionally not
committed upstream. Preserve private binary/decompilation provenance and do not
publish those inputs as part of adapting a test. No third-party binary or source
was copied into Raphael by this audit.

## Proposed roadmap disposition

Add source-audit completion as a research milestone, with these **open** tasks:
(1) intended-content versus raw-RFB visual oracle; (2) mixed CPU/GPU LOAD retention;
(3) biplanar IOSurface, mip/slice identity and cross-pass depth; (4) bounded heap
alias lifetime, distinct from proving page-table release. Retain stock-QEMU/SMC,
physical output, independent-host-boot and full lifecycle gates. Reims supplies
useful test hypotheses, not evidence closing those gates.
