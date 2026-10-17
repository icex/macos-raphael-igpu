# Candidate 185 offline investigation

Date: 2026-09-10

Scope was read-only source and frozen-capture analysis. No VM, device, sudo,
reset, build, staging, or host action was performed.

## Root cause evidence

Candidate 185 never observed Lilu dispatching the patcher callback before any
AMD driver correction was installed. Its serial has plugin startup at lines
208-223, but no `patcher ready`, `loadKinfo`, or `kext callback` record anywhere.
It then reaches the first
GPUCAP at line 1264 with the native bad aperture (`Base == Top == 0x100000000`),
BGM event `0xc00c0203` at line 1288, and the unpatched PPLIB `doGPUPanic` path at
lines 1504-1511.

Both candidate 183 captures show the working boundary. For example, GUI-183
records `patcher ready` and three successful `loadKinfo` calls at lines 457-460,
then the framebuffer callback and `m1 doGPUPanic`/PowerPlay/XGMI routes at
1562-1566. The X6000 and HWLibs callbacks install the remaining routes at
1652-1739. Consequently its first GPUCAP reports the corrected aperture
`0xf400000000..0xf41fffffff` at line 1763 and TTL proceeds through the remaps and
capability retry. This is earlier than every candidate-183 VMID2 behavior.

The functional callback/route code is unchanged from candidate 183. Pinned Lilu
1.6.8 rules out a registration-return or worker-order race: the plugin entrypoint
holds Lilu's API lock throughout `pluginStart()`, `finaliseRequests()` cannot pass
that lock concurrently, and both `*Force` wrappers panic on a non-success return.
Candidate 185 logs the statement after both calls, so both registrations returned
successfully. Moving those calls above `kernel_thread_start` would therefore not
address the demonstrated failure.

Lilu 1.6.8 defers `processPatcherLoadCallbacks()` until `performCommonInit()`.
On Big Sur and later, successful `performEarlyInit()` installs only a
`PE_initialize_console` hook and `registerPolicy()` returns without registering
the TrustedBSD fallback. Common initialization then requires
`PE_initialize_console(kPEEnableScreen)`. Candidate 185's intentional removal of
the generic display is the relevant launch-topology change, and its AMD drivers
execute before any `patcher ready` record. The strongest source-backed hypothesis
is therefore that headless/no-generic boot never supplied Lilu's screen-enable
trigger before AMD startup. Frozen evidence cannot prove whether it was absent
for the whole boot because the guest panicked first.

There is no built-in boot argument that bypasses this Big Sur console path.
`-liluslow` only changes which policy operation would be selected; successful
`performEarlyInit()` still returns before `policy.registerPolicy()`, so that
operation is never registered.

COM2 is a separate deterministic failure: `criticalDumpThread` sleeps the
configured `rgpudump=40000` before UART initialization and `RGPU_UART_READY`
(`src/RaphaelGPU.cpp:495-513`). The guest panicked roughly 14 seconds into its
driver path, so readiness could not appear. Repairing COM2 timing alone would
improve evidence but would not install the missing GPU patches.

## Smallest proposed fix and test

Do not reorder or replace the successful `*Force` registrations, add ramfb, or
restore a generic adapter. The smallest auditable correction is an opt-in patch
to the pinned Lilu 1.6.8 source: under a new explicit headless boot argument,
skip the Big Sur `performEarlyInit()`/console-hook return and register the existing
TrustedBSD policy path instead. Preserve its existing `policyLock` and
`initialised` once-only checks; use the existing `mpo_policy_initbsd` plus the
slow-mode `mpo_mount_check_remount` fallback, and call the unchanged
`performInit()`/`performCommonInit()` path. The option must default off.

This requires building and staging a pinned patched Lilu kext as its own sealed
input, not changing only RaphaelGPU's vendored headers. The repository currently
builds RaphaelGPU against the release resource tree and hashes that tree, while
deploy tooling treats `Lilu.kext` separately. A plan must therefore pin the Lilu
source commit/patch, resulting bundle and executable hashes, and exact ESP staged
hash alongside the candidate manifest.

Offline tests should exercise a factored choice function: normal Big Sur selects
the console hook; explicit headless mode selects policy registration; either path
can transition the once-only state at most once. A source integration check must
also prove headless mode retains `mpo_policy_initbsd` and the slow remount fallback.

The next single hardware test, only after normal safety/admission review, is
discriminating at the earliest boundary: require `patcher ready`, all three
`loadKinfo` successes, framebuffer/HWLibs/X6000 callbacks, the `m1` panic patch,
and corrected first GPUCAP before interpreting BGM, VMID1, or Metal results.
Absence of `patcher ready` rejects the headless policy-init correction without
another functional diagnosis. Later missing routes remain a separate route failure.
