# Candidate 417: paused during boot, relay runtime untested

The user requested a pause during the software-only BootI run on 2026-10-10.
Launch source was `049c6c6`; VM UUID was `9e78680e-d59b-475c-80ef-670a0be43b93`.
The initial screenshot shows Darwin boot text, not a usable desktop. No fixed
root-command response or process-admission receipt was produced. The hardened
process fix therefore remains native-runtime unqualified.

An ACPI request was issued, then the normal controller `stop()` helper performed
forced poweroff while the guest was still booting. This is not clean guest shutdown.
The controller remained alive to finish its receipts: final_state=poweroff,
unregistered=true, unregister_attempts=1, no reported cleanup error. Its service
became inactive. No GPU/VFIO exposure occurred and no GPU ledger entry was consumed.

Local validation before launch: 1496 tests ran, eight skipped, remainder passed
in 56.577 seconds (`run/c417-final-full-suite.log`). This does not establish relay
runtime success. Resume with a fresh independent clone/candidate and the same
bounded read-only relay test; verify actual UID0 framed output and guest contents,
then awake/normal shutdown evidence before framebuffer-ownership experiments.

Evidence lives in `run/c417-vbox-boot-i/`; companion manifest hashes the selected
receipts and boot screenshot. The pending goal is paused at the user's request.
