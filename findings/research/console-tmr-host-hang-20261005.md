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
