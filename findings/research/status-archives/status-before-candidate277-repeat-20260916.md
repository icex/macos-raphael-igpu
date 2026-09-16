# Live status — candidate 277 HEVC service-name fix

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, five exposures completed.
Candidate 276 run 84e8479030e7d41098a3751309dc2d26: CORE_PROBE_PASS,
exited-after-guest-request, recovered, no host kernel messages. GPU remains
vfio-pci, power/control=on.

User requests fixing HEVC decode with repeated testing. Extend this boot's
allowance by one exposure (sixth total): candidate 277 exact marked PCI IOService
rename S30 -> GFX0, fresh MODE2, manual-reuse/ack-risk, 6000s maximum, unchanged
identity, capture-fatal, host-fault, shutdown and recovery aborts.

276 proved the capability search skips the actual S30 GPU; the only display node
is an unrelated IOResources compatibility service with no codec properties.
Metal enumerates one accelerator with complete HEVC capabilities. Hardware-required
HEVC create fails -12913/-12906. The earlier supposed hardware decode success
was an explicitly SOFTWARE decode of a hardware-encoded stream.

277 hypothesis: naming the marked GPU GFX0 makes the existing recursive search
find its accelerator and permits HEVC context creation. Falsifier: GFX0 and
properties are visible but the same capability failure persists.

Full desktop/display and sustained codecs unqualified. No main merge or push.
Previous details in findings/research/status-archives/status-before-candidate277-20260916.md.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-277-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
