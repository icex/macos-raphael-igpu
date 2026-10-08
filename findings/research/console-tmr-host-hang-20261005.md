# Candidate332 host hang at PSP TMR teardown

Candidate332 run `dd40f35333452ac3e23f25210704f120`, source `0f29017`, metal-180,
followed the failed331 experiment on boot5074c0e5. The user reports a whole-host
hang. The next observed boot is ba51b3c6. There are no final shutdown/recovery
receipts for332. Preserved raw evidence is `~/macos-vm/run/candidate-332-host-hang/`.

## Observed timeline

- Candidate331 attached the Bochs console but printed `HOSTRESERVE: invalid
  framebuffer or DMCUB identity`, then refused PSP TMR initialization. No native
  GPU work started. Guest-request shutdown succeeded. The supported stopped-device
  MODE2/no-queue helper verified inactivity, destroyed PSP rings and authorized reuse.
- Candidate332 removed `rgpuhostreserve` while retaining console mode. MODE2#263
  returned CP_STAT=0/RLC_CNTL=0 and normal admission accepted the prior receipt.
- The console bridge attached. No userspace console mapping, capture or mode write
  had been requested. Serial reached PSP DESTROY_TMR (`wire=7`) and ended during
  the submission doorbell sequence. There is no unload return, native Metal
  startup or guest panic record afterward.
- Prior-boot kernel journal ends without an oops/AER/AMD-Vi message. No archived
  pstore file was available; direct `/sys/fs/pstore` listing was permission-denied.
  The hardware mechanism cannot be proven from this truncated capture.

## Diagnosis and correction

The first incorrect conclusion was that331's missing reservation was explained
by disabled DCN alone. The actual diagnostic includes an invalid firmware identity.
The second error was removing the reservation option instead of understanding
that refusal. This let332 execute TMR teardown without preserving or stopping
firmware that may reference that memory. MODE2 queue cleanup does not prove
DMCUB/TMR ownership. The failure boundary strongly implicates that unguarded path;
it does not prove the exact fabric/firmware fault or exclude every console effect.

Candidate333 makes console firmware ownership independent of HDMI enable flags:

- `rgpuconsole=1` automatically enables the native memory-reservation hook.
- The reservation path accepts the existing verified held-firmware identity, or
  uses the previously implemented bounded stop/reset/readback before replacing TMR.
- Immediately before the PSP operation, require successful reservation and live
  DMCUB enable clear, processor reset asserted and interface reset asserted.
  Missing/inaccessible state returns an error without submitting PSP teardown.
- The console path does not enable firmware reload/start or physical HDMI.
- Candidate332's staging profile is explicitly withdrawn. Its failed artifacts
  remain unchanged.

Offline fault injection covers absent ownership, all-ones reads, running firmware,
missing processor/interface reset, successful return propagation and state changing
between calls. These checks prevent the demonstrated configuration bypass; they
are not hardware validation of333 or universal host-hang protection.

## Validation and next observation

Candidate333 source `d4a4111` built as1.0.333 with debug symbols. The complete
host suite passed1026 tests (three skipped). The metal-181 profile validates;
metal-180 is refused explicitly. Build and test logs are
`~/macos-vm/run/candidate-333-build.log` and `~/macos-vm/run/c333-tests.log`.

No333 GPU exposure has occurred. On bootba51b3c6, amdgpu still owns7b:00.0.
Read-only fdinfo inspection found allocated VRAM/GTT held by VS Code and Codex
Desktop (the app-server inherits the same DRM client). These applications must
release the device before handoff; they were not killed or detached.
The next discriminating run must capture reservation success, live firmware hold,
PSP unload return, native Metal startup and independent shutdown/recovery receipts.
Passing offline checks alone does not establish that the host hang is fixed.


October8 follow-up: the user handed7b:00.0 to VFIO. The first333 cycle stopped
before staging on332's stale launch marker; it was archived under the preserved
crash directory after matching the old-boot supervision identity and absence of
its service/container. MODE2#264/#265 passed. The second attempt refused before
QEMU on missing boot-time initialization journal lines (journal begins October7).
Current-boot logs retain several complete amdgpu system-resume sequences.
The initialization parser now accepts the exact ordered Raphael resume sequence,
with all subsystem markers and PM completion, and rejects device failures and
partial/latest-incomplete resumes. This proves prior initialization only.
Source audit: local Linux `amdgpu_device.c:4678` resume calls IP resume and reports
`amdgpu_device_ip_resume failed` on failure. Regression fixtures cover missing
markers, wrong GPU, failures, reverse order and a later incomplete resume.
