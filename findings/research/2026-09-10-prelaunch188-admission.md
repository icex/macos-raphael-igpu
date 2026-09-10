# Candidate 188 prelaunch admission audit

## Verdict

The reported launcher path cannot open or write the VFIO device. In the live
launcher whose SHA-256 is pinned by the candidate 188 manifest
(`b3b3c32c7fb86f80760538b708c22f93878ebe0901b7cc2535cc250600b76a3f`),
the unconditional X11 socket test exits at `macos-vm.sh:119`. The GPU block does
not begin until line 190, `/dev/vfio/31` is only tested for access at line 200,
the VFIO device arguments are only constructed at lines 201--213, and `docker
run` is not executed until line 316. `vm-supervision.py` merely passes the
validated GPU flags to this child; it does not open VFIO itself. Before the
child, `experiment.py` performs identity and host-state reads, reserves the
ledger entry, takes a kernel cursor, starts the monitor, and creates the
supervisor's launch-pending record. None of those operations opens the VFIO
group or writes GPU registers.

The retained artifacts are consistent with that path: both serial captures are
empty, there is no `supervision.json` or `recovery-reservation.json`, the
classifier records `supervised launcher is not running`, host-before equals
host-after, and the kernel-message delta is empty. The current shared
`run/vm-launch.log` contains only `error: no X11 socket at
/tmp/.X11-unix/X0` and has SHA-256
`030f9cff7ff084563726911d2754a4aab32dee1abf4588935b0b00be8678b3e9`.

This establishes the code-path result, but the present evidence does not by
itself provide a durable, exact-attempt provenance proof. `vm-launch.log` is a
shared file opened with truncation on every launch; the output does not retain
the random `rgpu-launch-*` service name, its exact ExecStart, or a journal/unit
exit record. Equal host snapshots and an empty kernel delta corroborate absence
of observable damage, but cannot prove absence of a short VFIO open or write.
Therefore the existing historical 173/174 continuation must not be reused, and
the current artifacts alone should not automatically authorize a continuation.

## Minimal legitimate exception

A proof-validated continuation is legitimate only as a new, candidate-specific
one-shot admission. It should continue the already reserved run rather than add,
delete, edit, or replace any ledger row. It must use the same boot ID
`3bca3e47-1f28-4f78-af00-5dbf76b00620`, run ID
`cb1d0aadd8186205d867a23fe175c336`, exact manifest bytes (SHA-256
`5f6dcff73c1b7df66ffe9b78459aed88178a3a33f213310d20c23c25d3f89673`),
candidate, boot disk, image, ROM, harness identities, and unchanged diagnostic
contract. It must preserve the original output directory and its complete
inventory byte-for-byte and write continuation evidence to a new output
directory. It must not manufacture or accept a recovery receipt: this is proof
that the reserved launch never reached VFIO, not proof that an exposed GPU was
recovered.

Admission must require all of the following and fail closed:

- An immutable proof bound to the exact failed service: unique service name,
  full systemd ExecStart/argv and environment identity, start/end timestamps,
  exit status, and journal records showing the child emitted the exact X11
  failure before any container identity was published. The service identity
  must also bind the run ID and the supervisor/launcher hashes from the
  manifest. If this exact-attempt record cannot be recovered independently,
  reboot is the safe path.
- A frozen copy of the 42-byte launcher log, its hash, the original output
  digest/inventory, original verdict hash, exact ledger preimage hash, and the
  reservation row. A mutable shared log path is insufficient.
- Proof that no Docker container for the unique name or `macos-sequoia` was
  created, and no QEMU process/argv containing `vfio-pci,host=0000:7b:00.0`
  existed during the interval. A present-time `docker ps` check alone is
  insufficient; it must be exact-attempt history or independently retained
  audit evidence.
- A kernel-journal cursor taken before the failed launch and an exact bounded
  delta through cleanup with no VFIO reset, error, IOMMU fault, QEMU, or host
  fault indicators. Current clean host state must again pass the full normal
  host gate, with no active or pending launch units.
- Exact validation of the ordering property in the pinned launcher: the
  observed failure is unconditional and precedes every GPU block, copy of the
  ROM into the runtime path, Docker argument construction, container creation,
  and QEMU execution. Prefer a narrowly scoped static validator or pinned hash;
  accepting a free-form error string or line number is unsafe.
- An `O_EXCL` marker keyed by this boot ID and run ID, written only after every
  proof and live-state check and immediately before the continued launch. The
  validator must reject an existing marker, any ledger-byte change, any output
  mutation, any identity change, another pending/active unit, or any extra
  launch for this run ID. The marker is consumed even if the continuation also
  fails before Docker.
- The ordinary exposure deadline, host monitor, capture gates, shutdown, and
  recovery rules remain unchanged. Once Docker/QEMU starts, the attempt is an
  actual GPU exposure and requires the ordinary valid recovery receipt before
  any later same-boot use. The maximum-three ledger ceiling remains enforced;
  this exception grants no extra reservation and no rolling retry.

## Loopholes to reject

Do not generalize admission to “launcher failed before supervision,” “empty
serial,” “no active VM,” matching before/after snapshots, a selected stderr
substring, or absence of a recovery reservation. Each can also occur after a
container briefly opened VFIO and disappeared. Do not permit callers to supply
arbitrary proof paths or replacement manifests without compile-time/exact-hash
pins for this boot, run, manifest, original evidence, ledger preimage, and proof
schema. Do not infer non-exposure from the classifier's
`identity_or_route_missing`; that is a fallback classification, not launch-stage
evidence. Do not remove the existing reservation, decrement the count, append a
new row, or synthesize a startup/recovery receipt. Do not allow a second
continuation after the one-shot marker is created, even when that continuation
fails at another pre-Docker check.

The decisive distinction is that static ordering proves what follows from an
authenticated X11 failure, while durable provenance proves that this exact
reserved attempt actually encountered that failure. Both are required for a
same-boot continuation. Without the second half, a fresh boot is the only
admission consistent with the standing no-bypass rule.
