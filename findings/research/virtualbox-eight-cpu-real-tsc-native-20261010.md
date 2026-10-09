# Candidate403: eight-vCPU VirtualBox software desktop with host-offset TSC

Root-owned bootD UUID `13212bff-697a-473d-b257-da83e7e463b9` uses eight vCPUs and the supported RealTSCOffset clock regime. Actual logs show RealTSCOffset at4699997773Hz, matching calibrated host frequency. This is a coupled mode/frequency change from bootB's emulated4294967295Hz; it is not an isolated frequency-only or mode-only comparison.

## Observed function

`screen-040.png` shows the actual macOS desktop with Dock, application windows and Keyboard Setup Assistant. Root and the report author independently viewed that image. The retained UART contains no `panic(cpu` or `Non-monotonic time` marker. This passes the bounded desktop-boot observation with eight vCPUs, following bootB's eight-vCPU userspace panic and bootC's one-vCPU desktop/input success. It does not establish the clock bug's exact mechanism or long-term stability.

Root did not perform new input, awake-state or graceful-shutdown checks in403. Keyboard Setup Assistant remains visible; input usability is not inferred from the screenshot. BootC's keyboard marker/awake evidence is separate. No physical Raphael/VFIO device or Metal acceleration was used.

## Exact cleanup failure and later reconciliation

The controller reached its deadline and powered off the VM. Original result.json preserves final_state=poweroff and cleanup_error=VBoxCallError; guest_boot_qualified=false remains its automated scope. Root later verified exact UUID/configuration powered off, unregistered it in one attempt and confirmed absence from the private list. `root-cleanup-reconciliation.json` says guest_shutdown_natural=false and original_result_preserved=true. No natural guest shutdown is claimed.

The private command log shows expected unregister locked-session errors (`VBOX_E_INVALID_OBJECT_STATE`,0x80bb0007), followed by a **read-side showvminfo failure** during GUI teardown: “Failed to get a console object from the direct session (VBOX_E_INVALID_OBJECT_STATE)”, outer `VBOX_E_VM_ERROR`0x80bb0003, context LockMachine Shared in VBoxManageInfo.cpp:3328. The existing loop retried unregister errors, but its state query was outside that catch. This narrower observation explains the early VBoxCallError without asserting the15-second unlock deadline expired.

The controller correction classifies only that exact showvminfo diagnostic as transient. It retries only after a successful exact UUID/configuration/stopped observation already occurred in the same bounded loop, and issues no further unregister until another complete state observation succeeds. Initial ambiguous state, changed identity/running state and unrelated errors still refuse. The original15-second budget is unchanged; no forced session unlock, receipt synthesis or VM restart is added. Thirteen focused tests pass, including a stopped→query-transition→stopped sequence, initial-transition refusal, running-state refusal and exact error classification. Native qualification of this correction remains outstanding.

## Evidence and next boundary

The manifest hashes scope, actual clock selection, UART, desktop screenshot, original/reconciled cleanup and selected sanitized error lines. Full private command logs remain outside git and are hashed only. Next test should confirm input/awake and orderly GUI shutdown with no Terminal background awake job left blocking it, then qualify the bounded unregister fix. Actual VBox acceleration remains a separate unimplemented path; success here is a software desktop.
