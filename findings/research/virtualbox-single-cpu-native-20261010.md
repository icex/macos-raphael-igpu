# Candidate401: actual VirtualBox macOS desktop, one virtual CPU

Root-owned software bootC UUID1a0740c7-3655-481e-a5f5-e7dac76dee1e used independent disks and the identical bootB loader, changing vCPUs8→1 only. Recorded TSC mode/frequency remained VirtTSCEmulated4294967295Hz. No physical Raphael/VFIO device or macOS Metal acceleration was present.

The hardware owner visually verified the actual VirtualBox macOS desktop and Terminal screenshot `input-awake.png`: keyboard marker VBOX401_INPUT_OK, hw.ncpu1, build24G830, and pmset awake assertions. No monotonicity panic recurred through approximately238seconds. This supports an SMP contribution to bootB's timekeeping failure; one bounded success is not proof of its root cause, universal stability or a production single-core solution. The controller's unchanged guest_boot_qualified=false is its automated-result scope; independent visible/input evidence is recorded here rather than rewriting that result.

## Shutdown was forced, not natural

A guest sudo-n shutdown attempt required a password and did not execute. ACPI power button opened the shutdown dialog; root confirmed Return. Terminal then warned about the background caffeinate job (`screen-046.png`), preventing completion before the controller's deadline poweroff at about237.8seconds. The original result records poweroff plus cleanup_error=RuntimeError because immediate unregister raced the GUI session lock.

Root subsequently reverified the same UUID/configuration in powered-off state, unregistered it successfully and verified absence from the private VM list. `root-cleanup-reconciliation.json` explicitly retains original_result_preserved=true and guest_shutdown_natural=false. This is proven final software cleanup after deadline poweroff, not graceful guest shutdown and not GPU recovery. No privileged command bypass or receipt rewriting occurred.

## Next discriminator

Keep the achieved actual-hypervisor desktop/input milestone separate from the QEMU accelerated console. Source-audit the emulated clock's per-vCPU offsets/last-seen handling before choosing any8-vCPU timing change. The next controlled test must also stop/disown its own awake job before the normal graphical shutdown, then observe poweroff without deadline intervention. A bounded controller retry may wait for GUI unlock only while exact UUID/configuration remains powered off; errors and elapsed time must remain visible.

The accompanying manifest hashes the bounded screenshots, input/shutdown requests, UART, actual TSC observation and original/reconciled cleanup evidence. All VM operations were performed by root; this report adds no VM activity.
