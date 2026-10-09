# Candidate352: isolated KVM dirty-log paired writes

A bounded ordinary-RAM KVM test on Linux7.2.5-1-cachyos-bore demonstrates a
large first-write penalty caused by enabling/rearming dirty logging. This uses
no physical GPU, QEMU, guest OS, network, disk, or firmware. It creates its own
VM/vCPU through /dev/kvm, runs a flat32-bit REP STOSD followed by HLT, then closes
all owned descriptors normally. The60-second alarm was not reached; exit0,
empty stderr, COMPLETE receipt. No native VM was touched.

| Bytes | Logging | First write median ms | Second write median ms |
|---:|---:|---:|---:|
|8294400|off|0.275|0.274|
|8294400|on|3.452|0.299|
|33177600|off|1.091|1.095|
|33177600|on|14.407|1.118|

Each size uses off/on/off/on passes, six pairs per pass; table excludes pair0
from each pass (ten remaining pairs per configuration). All48pairs verify every
written uint32 after each guest write, outside timing. The guest sees an identical
ordinary RAM range at GPA0x200000. With logging enabled, GET_DIRTY_LOG before the
pair clears/rearms tracking, and the postpair bitmap must contain every page
(2025 or8100). Manual dirty-log protection is deliberately not enabled. Host
wall time around KVM_RUN includes kernel/vCPU overhead and scheduling, not just
instruction execution. Host readback changes cache state identically across
configurations; these are protocol-specific results, not memory bandwidth limits.

The controlled change establishes that dirty logging can independently produce
the observed slow-first/fast-second pattern at similar magnitudes on this host.
It does not prove current Bochs refresh causes every native copy delay: no WC/PAT
mapping, SPICE viewer, periodic midpair dirty clearing, SCK source or QEMU manual
protect mode was included. In particular the33MB second write is cheap here;
repeated16ms native costs still need refresh-cadence correlation or an isolated
QEMU/Bochs control. No production patch follows from this test alone.

Reproduce (software KVM access required, no sudo):

```
cc -O2 -Wall -Wextra -Werror tools/kvm-dirty-pair-probe.c -o /tmp/kvm-dirty-pair-probe
/tmp/kvm-dirty-pair-probe
```

Raw retained run: `~/macos-vm/run/c352-dirty-pair/` with binary/output/error and
result.json. Repository evidence contains raw output and artifact SHA256 values.
Compilation with warnings-as-errors, all readback/bitmap checks and diff check
pass. The complete project suite was not rerun for this independent research tool.
