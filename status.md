# Live status —2026-10-10

## Candidate399: host copy timing isolated; no optimization

Run1849f3959a4a38e15836c9364554f76f, launchfd6dc6f,
buildf868a8dae9664e469b2011390547c5ca, built-fromb7e17c0.
Strict host/guest analyses accept20steady4K windows8..27 and4691commits each.
Host means: allocation0.02058ms, copy including first-touch6.834ms,
pending-free0.09521ms (339occupied/4691calls). Guest copy1.556ms,
doorbell6.983ms, ACK1.468ms. Independent clocks/windows are not phase-aligned.
This identifies measured cost, not an optimization/performance gain.

Actual manager4036unique tokens/100.006s,0invalid/duplicates; phase5short tail
notqualified. TOKEN_DONE retained. c399-desktop.png is the WRONG focused host
window and excluded as desktop proof; observer RuntimeMax180 expired beforelate
capture. No399post-workload desktop-return visual qualification ornewinput/audio.

Shutdown exited-after-guest-request/private_terminal_verified=true. Private
terminal guest-shutdown/process_exitedtrue. Both capture receipts exactly
container-stopped-during-shutdown-wait/deferred/eventwaittrue~0.588s, consoleEOF,
criticalrecv-reset. Independent Docker die0/destroy/noKill supports naturalexit.
Recovery recovered/authorizes_launch=true. CR2snapshot18/365 records,
0corrupt/0incomplete with terminal-prefix tolerance. NoGPUcycle remainsactive
from399; root owns subsequent software/hardware operations.

Evidence: findings/research/console-host-snapshot-timing-native-20261010.md
and26-artifact manifest; run/candidate-399-results,c399-timing-analysis.json.
PrivateQEMUlog stays0600outsidegit/hash-only. Earlier397normaldesktop screenshot
is historical; do not substitute it for399missingvisualproof.

Last delivereddev c1f64d0/tested395 hostedCIgreen; mainunchanged.
Next separate host copy/first-touch/ownership cost before optimizing. TrueVBox
bootB separately reacheduserspace thenmonotonic-timepanic;401singleCPU test
rootowned, noVBoxaccelerationclaim. Preserve naturalcompletion andforcedabort
asdistinct outcomes in every furthercycle.
