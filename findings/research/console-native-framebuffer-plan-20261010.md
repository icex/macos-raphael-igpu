# Candidate433: owned native framebuffer prototype

Candidate432 established native120Hz mode metadata with a30Hz CVDisplayLink
period in the same process. Adding EDID labels cannot supply the missing VBL.
This prototype implements an owned IOFramebuffer for QEMU Bochs; the Raphael
iGPU remains the Metal rendering device. No Apple binary or physical GPU firmware
is modified. This document is a research plan, not runtime qualification.

## Implementation

`src/ConsoleFramebuffer.cpp` supplies32-bit RGB pixel information, aperture bounds,
fixed60/120Hz modes, detailed timing with64-bit pixel clocks, and a software timer
invoking the registered public IOFBInterruptProc(target,ref). It does not write
private IOFramebuffer shared offsets. The timer uses absolute fractional deadlines,
skips missed ticks, and avoids a second arm after callback reentry reschedules it.
Mode changes, callback registration, enable/disable and stop serialize on one
workloop command gate. Callback targets are retained; opaque interrupt handles
are generation-specific. Partial-start cleanup tracks actual gate/timer attachment.

Probe requires opt-in rgpunativefb=1, exact1234:1111/class038000 and subsystem
1af4:1100. It matches IOMatchCategory=IOFramebuffer with score60000. Actual432
IORegistry shows AppleBochVGAFB in that category with score30000. RaphaelConsole
uses the independent default category; its source is unchanged. Runtime must
verify exactly one attached framebuffer and one bridge on the expected PCI node.

The table includes standard1080p,1440p,4K and5K at60/120. Actual available modes
are bounded by BOTH BAR0 and negotiated snapshot transport capacity. Current32MiB
transport admits through4K and excludes5K. The64MiB prototype on431 is not yet
integrated. Retina variants require actual macOS mode enumeration; dynamic window
resize requires a later programmable-mode/connect-resense implementation.

The external support launcher now suppresses holder/SCK helpers when the owned
framebuffer reports NativeConsoleReady. Otherwise it follows the original path.
Install that launcher BEFORE enabling the native driver: simultaneous native
mode selection and snapshot-publisher VBE programming is not an admissible test.
The capture-app seal remains unchanged by this external launcher update.

## Offline evidence and runtime gates

The prototype compiled/linked against the pinned MacKernelSDK in release/debug
ABI builds. Those provisional archives retain432 version and dirty-source metadata;
they must NOT be staged. The actual433 card/version/build identity remains to prepare.
Compiled policy tests exercise exact32/64MiB bounds and one hour of60/120 fractional
deadlines, late-tick skipping and overflow refusal. They do not prove kernel
callback lifetime, mode acceptance, actual delivery or hardware recovery.

Next: seal the433 preparation build with the native boot option disabled, install
the launcher guard in the guest, retain an authorizing recovery receipt, then
enable the driver on a fresh candidate. Wait for harness probe completion before
using the shared guest-command relay. Test native output with both holder and
presenter absent, then read mode/pixel-clock properties and actual display-link
cadence. Any unknown framebuffer identity, mixed mode owners, missing capture,
hang or failed cleanup prevents qualification. A120Hz synthetic VBL clock still
does not prove120 distinct delivered frames or physical scanout.

## First preparation run

433 run4061015c26310a92abfa72f4c0a4a077 panicked during OSKext::start before a
build marker. Native option absent; disabling probe does not isolate link/import
changes. Archive has1.0.433 kmod and normal RX text; panic lists1.0.3/8192bytes.
Fault0x10 is a non-present instruction fetch, not proven NX protection rejection.
Investigate injected/prelinked metadata and dependencies before altering segment
permissions or guest caches. Launcher guard installation did not occur.

Exact supervisor stop preserved the runner; wrapper capture was INVALID. Normal
recovery lacked critical readiness. Separate supported schema9 stopped/noqueue
recovery returned recovered/authorizes_launch=true with no host faults. See
`console-native-framebuffer-loading-evidence-20261010.json`. Tests and the sealed
build do not qualify kernel loading or native framebuffer functionality.
