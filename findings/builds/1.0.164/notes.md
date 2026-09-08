# Candidate164 prepared — 2026-09-08

Built from clean source827188a. Exact build and executable hashes are recorded
beside this note. The source-built executable now matches kext/bin/RaphaelGPU.
The bundle was inserted transactionally into the raw ESP, read back, converted
into the actual QEMU bootdisk, and verified from a converted copy of that qcow2.
Both prior images were preserved as backups. No VM was launched during staging.

Validation: 77 Python regression tests, native cross-compile, exact24G830 KDK
symbol/prologue/patch-pattern checks and route-domain checks passed. The new
selector ABI/entry and classifier target requirement were independently reviewed.
Only existing SDK deprecation/framework-directory warnings occurred in the build.

This build has not been hardware-tested. Prepared inputs remain under the explicit
VM directory at run/candidate-164. After a user reboot, verify fresh amdgpu state,
restore the unprivileged sleep inhibitor if needed, and prepare hybrid-002 with
that boot ID before one-way handoff. Do not reuse hybrid-001's manifest, rebuild
an identified candidate in place, or clear the previous boot's use reservation.
The probe was already compiled GPU-less; no compilation is needed during exposure.
