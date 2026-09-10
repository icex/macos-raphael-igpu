# Candidate 188 recovered prelaunch evidence: admission decision

## Decision

The recovered evidence is sufficient to establish that candidate 188's reserved
attempt did not create a container, start QEMU, open VFIO, or write the GPU. A
single candidate-specific continuation of the existing reservation is therefore
defensible, provided the admission implementation pins every item below and
retains all ordinary host, deadline, capture, cleanup, budget, and recovery
guards.

The evidence chain is concrete:

- `findings/research/2026-09-10-candidate188-prelaunch-evidence/SHA256SUMS`
  freezes the original manifest and output evidence, the 42-byte launcher log,
  and the exact failing `macos-vm.sh`, `vm-supervision.py`, and `vm-entry.sh`.
- The exact service journal identifies
  `rgpu-launch-f356b4cfc9a0451a9afda1e4dfb206f0`, invocation ID
  `3d4b03acac054b10b63dd7a842db319f`, PID 25105, and the full command with GPU
  `0000:7b:00.0`, ROM, critical serial, and 180-second cap. It started at
  realtime timestamp 1789060599622815, reported that the launcher exited before
  container identification, exited status 1, and was stopped by
  1789060599863115: a 240 ms lifetime.
- The frozen `vm-launch.log` has SHA-256
  `030f9cff7ff084563726911d2754a4aab32dee1abf4588935b0b00be8678b3e9`
  and contains exactly `error: no X11 socket at /tmp/.X11-unix/X0`. Its mtime is
  inside the exact service interval. The frozen supervisor shows that this
  invocation opens that log, launches `macos-vm.sh`, and emits the journaled
  refusal when the child exits before Docker identification.
- The failing launcher hash is
  `b3b3c32c7fb86f80760538b708c22f93878ebe0901b7cc2535cc250600b76a3f`.
  Its unconditional X11 check exits at line 119. Its GPU block starts at line
  190 and Docker execution occurs at line 316. Thus an authenticated line-119
  exit cannot reach VFIO argument construction, ROM copying, container
  creation, or QEMU.
- A Docker event query bounded around the exact service interval returned no
  events. Its output and exact `--since`/`--until` arguments must be frozen and
  hashed into the proof before admission. This is the concrete historical check
  that closes the possibility of a briefly created and removed container.
- Empty captures, no `supervision.json` or recovery reservation, identical
  valid host-before/after snapshots, and an empty bounded kernel-message delta
  corroborate the primary service, launcher, and Docker evidence.

Any GPU-less Docker activity after this bounded interval is irrelevant to this
finding. The validator must use the exact realtime/monotonic service bounds and
must not replace them with an interval broad enough to include later GPU-less
qualification activity.

## Exact continuation scope

The continuation must preserve boot ID
`3bca3e47-1f28-4f78-af00-5dbf76b00620`, run ID
`cb1d0aadd8186205d867a23fe175c336`, the original evidence bundle, candidate,
media, boot arguments, launch contract, and the existing reservation. It must
not create a recovery or startup receipt and must not append, remove, edit, or
replace a boot-ledger row.

The file named `candidate-188-staging-ledger.json` in the frozen bundle is the
staging transaction record, not the boot-use ledger. The actual current boot
ledger is
`/home/bogdan/macos-vm/run/used-gpu-boots/3bca3e47-1f28-4f78-af00-5dbf76b00620.json`:
220 bytes, SHA-256
`a77043b05bec577bec12a7fba397621aeed4a5267239357477c44982386cc2a1`, schema
2, maximum 3, and exactly one reservation for this run at epoch
1789060599.6137867. Those exact bytes need to be copied into the new immutable
proof bundle and hash-listed before admission. The validator must compare the
live ledger byte-for-byte immediately before consuming the continuation marker
and again immediately before launch.

Requiring an unchanged harness and byte-identical manifest would incorrectly
forbid the X11 repair. Exactly two prepared-identity deltas may be admitted:

1. `harness_sha256["macos-vm.sh"]` may change from the frozen failing hash to
   one reviewed and explicitly pinned repaired-launcher hash.
2. `source_commit` may change to one reviewed and explicitly pinned coordinator
   commit containing the admission and launcher repair.

No other field may differ. In particular, `source_sha256`, candidate executable
and Info.plist hashes, build ID and provenance, candidate directory, boot disk,
config, ROM, image ID, QEMU version, `vm-supervision.py`, `vm-entry.sh`, every
other harness hash, recovery helpers, boot arguments, launch options, experiment
card, boot ID, run ID, deadline, and capture contract remain identical. The new
manifest bytes and the complete field-level delta from the original must be
hash-pinned. The coordinator commit exception cannot authorize a changed driver
source digest or rebuilt candidate.

Admission then consumes one `O_EXCL` marker keyed to this exact boot and run.
The marker is one-shot even if the continuation stops before Docker. Once the
continued attempt creates Docker/QEMU, it is an actual GPU exposure; any later
same-boot reuse requires the ordinary valid recovery receipt. The existing
maximum-three ceiling remains unchanged and this exception grants neither a
new ledger reservation nor a rolling retry.

## Rejection conditions

Refuse on any missing or changed proof hash, non-exact journal identity or
interval, Docker event in the failed interval, unavailable/unfrozen Docker
event result, original-output mutation, ledger-byte mismatch, unexpected
manifest delta, unpinned launcher/commit, existing marker, pending or active GPU
launch, or failure of the full live host gate. Do not accept an error substring,
empty serial, clean present-time Docker listing, equal host snapshots, or the
classifier's fallback verdict as a substitute for the combined exact service,
static ordering, and historical Docker evidence.
