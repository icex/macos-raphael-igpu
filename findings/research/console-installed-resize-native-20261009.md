# Candidate386: installed resize with USB-tablet input

Run `e5d5d205577125364146f54224bbd3f6`, metal213, build
`ded62ba27d244bf892d516099cc7335d`, source `17e9077`.
This report covers completed functional observations; independent audio restoration,
final reconnect and shutdown/recovery remain pending at this revision.

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
route restoration is pending here; endpoint audibility and A/V synchronization are
not established by spectral capture.

## Limits and remaining work

The holder still uses fixed HiDPI2 guest modes. Actual host GDK1 therefore makes
UI physically large despite exact pixel-size agreement; adaptive DPI policy is a
separate unimplemented feature. Candidate385's eleven-size bounded LRU control is
prior evidence, not a repeated386 stress test. Broader crash/restart lifecycle,
first-user installation, other VM managers, VirtualBox, universal60Hz, and complete
frame integrity remain open. Final reconnect, audio-restoration and cleanup results
must be added before delivery is called complete.
