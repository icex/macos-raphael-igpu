# Deterministic early GDB rendezvous design

> **BLOCKED / ARCHIVED:** This is historical research for an unqualified
> implementation that has been removed from the active tools. Candidate 191
> uses the known-booting dynamic-slide `GDB=on` path and has no early-rendezvous
> mode or fixed-slide requirement. Do not use the procedure below as a current
> launch plan; see “Frozen `slide=0` qualification limitation” for the failure
> evidence.

## Problem and root cause

Candidate 190 used `GDB=on`.  In the pinned launcher this adds QEMU's TCP
gdbstub, but it does not stop any vCPU:

```text
GDB=on   -> -gdb tcp:0.0.0.0:1234
GDB=wait -> -S -gdb tcp:0.0.0.0:1234
```

The bounded runner then waited for the serial kernel mapping and exact Raphael
build-id line before it attached.  The first VMID1 prepare could therefore run
before the breakpoint was armed.  Starting the runner sooner narrows this race
but cannot remove it.

Changing only `GDB` to `wait` is insufficient.  The guest cannot publish the
serial mapping or build-id while QEMU is stopped at reset, so the current
serial-first runner would deadlock.  The current boot arguments also do not
contain `slide=0`; the statement in `/home/bogdan/macos-vm/gdb-attach.sh` that
addresses match link-time addresses is stale for candidates 188 through 190.

## Exact 24G830 rendezvous boundary

Use the isolated kernel executable already qualified for GDB:

```text
/home/bogdan/macos-vm/run/gdb-source-kext-prep-20260910T204500Z/kernel.symbols
SHA-256 04a501246caf768356f4090a8fd662daf5bbc949993353526c66771f5ba1d8e4
UUID f6a1b3d41ebb3628a1c589506c51ddec
```

In that exact binary, `OSKext::start(bool)` is at
`0xffffff8000970230` and starts with
`55 48 89 e5 41 57 41 56 41 55 41 54 53 48 83 ec 18`.
The 24G830 disassembly establishes the current-kext linkage without calling a
guest function from GDB:

```text
OSKext::start entry: rdi = OSKext *
OSKext + 0x50: kmod_info *
kmod_info + 0x10: 64-byte bounded name
kmod_info + 0x9c: executable address
kmod_info + 0xa4: executable size
```

The `+0x9c/+0xa4` interpretation is independently visible in
`OSKext::start+0x170`, immediately before the runtime initialization path.
The breakpoint is at function entry, before the indirect start callback at
`OSKext::start+0x248`, so a stop for the Raphael kext precedes Raphael/Lilu
plugin execution and therefore precedes `wrapVmmPrepare`.

## Proposed flow

1. A separately reviewed diagnostic card pins the existing functional boot
   arguments plus `slide=0`, selects `GDB=wait`, and preserves all exposure,
   identity, recovery, and cleanup deadlines.  This is a diagnostic topology
   change and needs a new card/candidate identity; it is not a retry of 190.
2. The runner validates the exact supervised CID, gdb port mapping, deadline,
   kernel-symbol SHA-256/UUID, Raphael executable/dSYM UUID, wrapper symbol,
   native call offset, and executable prologue before invoking GDB.  It does
   not wait for serial while QEMU is stopped.
3. GDB attaches to the `-S` stop, loads only the isolated kernel executable,
   and arms one hardware breakpoint at the pinned `OSKext::start` address.
   It then continues.  There is no monitor `stop`, timer, sleep, or GPU write.
4. At every `OSKext::start` stop, GDB first validates the runtime kernel Mach-O
   UUID and the exact `OSKext::start` prologue.  It reads only the bounded
   `this+0x50` kmod record.  Invalid pointers, noncanonical addresses, short
   reads, malformed names, or an executable range overflow are terminal capture
   failures rather than reasons to resume silently.
5. Non-Raphael kext names resume.  Bound the number of such stops to 512 and
   retain the unchanged experiment deadline.  The accepted name is the exact
   candidate-190 observed kmod name `as.rgpu.RaphaelGPU`; suffix matching and
   historical aliases are not sufficient at this identity boundary.
6. For the accepted current kext, validate the runtime executable's Mach-O UUID
   against the candidate binary, require the wrapper address to fall inside the
   recorded executable range, and compare the exact generated wrapper prologue.
   Only after all checks pass should GDB add the candidate dSYM and arm the
   existing VMID1 wrapper breakpoint and disabled native breakpoint.
7. Remove the `OSKext::start` rendezvous breakpoint before continuing into the
   Raphael start callback.  The existing VMID1 filter and stack-frame identity
   checks then capture actual CPU data at wrapper entry, native-call boundary,
   and wrapper return.  The transcript retains the existing statements that
   register programming and GPU completion are unestablished.
8. After the guest resumes, serial remains a required independent identity
   check.  Before accepting a complete result, the runner must observe the
   fresh runtime kernel mapping and exact candidate build-id on the CID-derived
   live serial path and require the mapping to equal the `slide=0` address used
   by GDB.  A complete GDB transcript without this later serial check is invalid.

## Why the alternatives are weaker

Attaching after a serial marker retains the original race.  QEMU monitor `stop`
or a timed pause is not tied to guest execution and can stop after the first
prepare.  A breakpoint on the dynamically addressed Raphael wrapper cannot be
installed at reset without either a fixed slide plus a loader rendezvous or an
unauthenticated address assumption.  Walking the global kmod list at an
unrelated loader stop can find Raphael after its start has begun; reading the
current `OSKext` argument avoids that ambiguity.

## Required offline tests

- Reject early mode unless kernel SHA-256, kernel UUID, kernel rendezvous
  address/prologue, exact Raphael binary/dSYM UUID, wrapper prologue, and native
  call offset are all supplied or derived from pinned artifacts.
- Generated-script fixture must place `target remote`, the rendezvous `hbreak`,
  and `continue` before any serial-dependent operation; it must not read the
  global kmod list to select the current kext.
- Generated-script fixture must contain the exact 24G830 address, prologue,
  `this+0x50`, name/address/size offsets, 512-stop cap, overflow checks, UUID
  validation, and removal of the rendezvous breakpoint before arming the wrapper.
- Runner fixture for `GDB=wait` must invoke the generator/GDB before serial text
  exists, then require the post-resume serial kernel mapping and build-id before
  writing `complete: true`.
- Negative fixtures cover wrong CID/port, non-wait supervision identity, expired
  deadline, wrong kernel UUID/prologue, malformed current kmod pointer/name,
  wrong Raphael UUID/prologue, wrapper outside executable range, rendezvous cap,
  absent later serial identity, and incomplete wrapper/native/return markers.
- Existing `GDB=on` scenarios either remain explicitly legacy or are rejected
  for `vmid1-root`; no implicit fallback from early mode to late attachment.

Offline fixtures establish script ordering, artifact identity, and bounded
failure behavior.  Only a reviewed hardware cycle can establish that QEMU's
hardware breakpoint survives the reset-to-long-mode transition and stops at the
24G830 `OSKext::start` boundary before the first Raphael callback.

The opt-in runner takes the coordinator-reviewed manifest path and its expected
SHA-256.  The manifest must share the write-once supervised output directory,
must contain the exact `GDB=wait` headless launch contract and one `slide=0`
word, and the exact running CID's container environment must independently
contain only `GDB=wait`.  This prevents an unrelated JSON file or a CLI boolean
from asserting the early-launch contract.

After a reviewed card has created a write-once manifest with `GDB=wait` and
`slide=0`, the offline-qualified invocation shape is:

```sh
python3 -B tools/run-bounded-gdb.py \
  --supervision <run-output>/supervision.json \
  --manifest <run-output>/manifest.json \
  --expected-manifest-sha256 <reviewed-64-lowercase-hex-sha256> \
  --output <new-gdb-output-directory> \
  --build-id f504d465bddf4a0aa0edcc9b57d2b4ef \
  --gdb <qualified-gdb> \
  --generator tools/gdb-kext-source.py \
  --kernel-symbols /home/bogdan/macos-vm/run/gdb-source-kext-prep-20260910T204500Z/kernel.symbols \
  --raphael-binary /home/bogdan/macos-vm/run/candidate-190/RaphaelGPU.kext/Contents/MacOS/RaphaelGPU \
  --raphael-dsym /home/bogdan/macos-vm/run/candidate-190-dist/debug-symbols/RaphaelGPU.dSYM \
  --scenario vmid1-root --early-rendezvous
```

This command is a reviewed future-run recipe.  It must not be applied to the
frozen candidate-190 run or used to create a launch without the normal
experiment authority and recovery gates.

## Frozen `slide=0` qualification limitation

Do not execute the fixed-slide flow above until the boot failure is resolved.
The frozen qualification serial file is append-only: lines 1--1490 contain an
older Darwin boot, while the supervised CID `a25dfcc6c1db...` attempt begins at
line 1491 and is identified by the OpenCore timestamp `2026-09-10T15:51:09`.
That attempt reaches the boot-kernel-collection map, then reports `[EB|STOP]
0x16`, `OC: Boot failed - Aborted`, and `OCB: StartImage failed - Aborted` at
lines 1686--1696.  It never reaches that attempt's `HANDOFF TO XNU`, KASLR, or
Darwin marker.  Later menu retries repeat after GDB has detached.

The debugger transcript also excludes breakpoint-memory corruption as the
mechanism for that attempt.  It requested a software breakpoint at the then
unmapped `0xffffff80004509e0`; QEMU/GDB returned `Cannot insert breakpoint 1`
and detached.  No breakpoint byte was installed.  The frozen notes identify
`slide=0` as the intended configuration difference and the later successful
qualification restored the known-booting configuration without it.  This is
strong evidence against repeating the fixed-slide plan, but the archived
directory does not isolate `slide=0` as the sole causal variable: it contains
multiple launch records and an appended serial file.  A new candidate must not
treat the old failure as proof that a particular fixed runtime address works.

For candidate 190, the fresh serial values have the internally consistent
relationship:

```text
runtime kernel __TEXT       0xffffff8002ae8000
reported KASLR slide      - 0x0000000002800000
unslid KC __TEXT            0xffffff80002e8000
KDK Mach-O __TEXT link    - 0xffffff8000200000
KC relocation within image  0x00000000000e8000
total KDK symbol relocation  0x00000000028e8000
```

Consequently the candidate-190 address corresponding to the pinned KDK
`OSKext::start` symbol `0xffffff8000970230` would be
`0xffffff8003258230`, not its link address and not merely link plus the printed
KASLR slide.  This calculation is historical evidence only; the runtime Mach-O
UUID and prologue still have to be read and authenticated before use.

There is currently no demonstrated deterministic replacement that can be
armed at reset with KASLR enabled.  QEMU documents unlimited hardware
breakpoints only for TCG; this launch selects KVM first, whose x86 guest-debug
path uses the architecture debug registers.  Therefore a fan-out over every
possible KASLR slide cannot be assumed to fit and has not been qualified.
Waiting for the fresh serial KASLR line and interrupting immediately avoids an
arbitrary timer, but retains a scheduler race and therefore does not meet the
deterministic pre-kext requirement.  An earlier fixed-address booter or loader
boundary would require pinned OpenCore/boot.efi symbols plus runtime relocation
and prologue evidence; none is present in the frozen evidence.  Until one of
those paths is established offline and then hardware-qualified, the early GDB
plan remains blocked.
