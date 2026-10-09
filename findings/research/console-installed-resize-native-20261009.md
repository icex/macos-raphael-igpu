# Candidate386: installed resize with USB-tablet input

Run `e5d5d205577125364146f54224bbd3f6`, metal213, build
`ded62ba27d244bf892d516099cc7335d`, source `17e907790afba76b50976da674ae75a6a411cc72`.
This report covers completed functional observations and shutdown/recovery.
Card213 used the ordinary presenter; experimental snapshot ownership remained unarmed.

## Installed startup and unchanged consent-bearing application

`run/c386-persistence.txt` records a new guest boot
`6A97FB22-D9FD-4639-A869-F257061672A1` with automatic startup of installed payload
`4d424e4034ed6cf6a1f44bd6490e52406fa8d9f25cb1e1ac59692a8f7daf3a46`.
Holder612, presenter769 and agent768 run without reinstalling the addon. The sealed
application, capture receipt, and CDHash remain identical to candidate385.
This is existing-user installed persistence, not first-user consent qualification.

The admitted QEMU profile explicitly sets `agent-mouse=off`: standard SPICE
monitor requests reach the resize agent while absolute pointer input retains the
USB-tablet path. Candidate385's agent-off isolation and pinned routing-source
analysis are preserved in [the prior report](console-arbitrary-resize-20261009.md).

## Actual manager resize and input controls

`c386-input-manager-events.jsonl` records actual manager1460×960 then1440×960
surfaces matching the requested viewports. `c386-input-positive-result.txt` records
passed:true, five target hits, zero misses, and the exact fixture token. Agent768
still owns the SPICE port; holder612 and presenter769 remain the same processes.
Thus the positive control exercises resize and pointer delivery together, rather
than disabling the agent to recover input.

Fixture source `a07a2a1` distinguishes unchanged screen notifications from actual
geometry transitions. The positive case retains one unchanged notification and
zero actual changes. The negative control `c386-input-negative-result.txt` completes
all five hits and exact text, but correctly returns passed:false for four actual
geometry changes even though final geometry is restored. This prevents final-mode
agreement from hiding disruptive changes during the input test.

`c386-audio-result.txt` passes isolated VM USB/QEMU/Pulse sample delivery. Independent
`c386-audio-restored-independent.json` confirms sink, volume, mute, defaults and
owned-module removal all restored; endpoint audibility and A/V synchronization are
not established by spectral capture.

## Limits and remaining work

The holder still uses fixed HiDPI2 guest modes. Actual host GDK1 therefore makes
UI physically large despite exact pixel-size agreement; adaptive DPI policy is a
separate unimplemented feature. Candidate385's eleven-size bounded LRU control is
prior evidence, not a repeated386 stress test. Broader crash/restart lifecycle,
first-user installation, other VM managers, VirtualBox, universal60Hz, and complete
frame integrity remain open. Cleanup receipts are recorded below.

## Geometry boundary and reconnect surface check

Accepted requests are even physical widths640..3840 and heights480..2160.
The holder uses fixed HiDPI2; an odd physical viewport request is refused, not
a promise of literal any-size resizing. Both current manager sessions report
GDK1. Adaptive guest-DPI selection and a defined odd-size policy remain concrete
roadmap work.

`c386-reconnect-manager-events.jsonl` records actual GDK1 viewports1502×960 then
1440×960 with matching settled pixbuf dimensions. This qualifies reconnect resize
for those requests; its input result is completed below.

## Reconnect input, restoration, and retained errors

`c386-input-reconnect-result.txt` passes five hits, zero misses, exact text
`RGPUD72C039B` and zero actual geometry changes. Holder612, agent768 (tty fd5),
and presenter769 remain unchanged. `c386-viewer-close-alive.json` verifies the
exact VM remains alive after viewer closure. `c386-final-state.txt` records
successful restoration to3840×2160.

`c386-final-capture-identity-user.txt`, executed as the owning user501, verifies
the same complete application hash, receipt and CDHash recorded at startup. The
earlier root invocation in `c386-final-capture-identity.txt` failed its ownership
check; retain this observer error rather than interpreting it as a changed seal.

Decoded `c386-final-{display,presenter,vdagent,launcher}.log` retain one
ConnectionRefusedError on request8 while direct geometry control was running.
Subsequent requests succeed. Two zero-monitor requests are unsupported refusals.
The run is not universally error-free; concurrent direct control is not qualified
as a reliable multi-client operation. Cleanup receipts are recorded below.

## Completed shutdown and capture boundary

Harness shutdown is exited-after-guest-request. The private libvirt terminal
records guest-shutdown with process_exited:true. Docker events contain container
die(exit0) and destroy, with no container kill/stop; an exec-helper137 is a
distinct event, not the VM exit code. Both capture receipts report deferred
natural-container-exit after about0.401s, shutdown_event_wait:false and
completed_original_zombie:false. Console records clean EOF; critical records
recv-reset, which remains an error transport boundary rather than being called EOF.

Recovery is recovered and authorizes_launch:true. Critical snapshot18 is a
terminal prefix, retaining one invalid-chunk-bounds line and incomplete snapshot7
with318 valid chunks/no END. Clean shutdown and authorizing recovery therefore
do not mean a perfect capture tail. The completed manifest includes these
independently hashed receipts.
