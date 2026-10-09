# Candidate369 software snapshot boundary result

**Observed:** a separate staging BAR plus synchronous ACK preserves acknowledged
pixels after immediate staging/BAR0 overwrite. Immutable host snapshots alone
still produced invalid sampled SPICE tokens; the separate single-bounding-box
control eliminated those invalid samples in this bounded software run.

This is paused TCG/qtest and an offscreen SpiceDisplay, with no physical GPU,
KVM, macOS, real manager window or deployed image change. Native WC ordering,
guest ownership/mapping code and presenter integration remain unqualified.
[Protocol and source ownership audit](console-snapshot-plan-20261009.md) ·
[Artifact hashes](console-snapshot-software-evidence-20261009.json).

## Exact software results

Final snapshot binary SHA256
`ebfe955a3f16e90c1a096c35dbea357152697e11492905eab34eaacffd7235ac`;
with separate single-bounding-box patch
`b03ed0a7fca6252a90bc9838d0fd5f7631498932419d86ca98ba3bc23903eb9e`.
Both are host-built research binaries, not native-compatible container artifacts.

`run/c369-snapshot/pixels-final-2` verifies full QMP RGB pixels at640x480,
1920x1080,3840x2160 and800x600 after reading ACK then overwriting both staging
and legacy BAR0, and changing VBE back to640x480. Repeat screenshots remain
unchanged. Legacy pixels before ARM/after DISARM pass. Duplicate sequence and
oversize geometry leave ACK unchanged. Re-ARM is refused. Two pending commits
produce one replacement; final counters report five publications and last seq6.
QEMU exits0. The uniform RGB pattern proves preservation throughout the surface,
not independent channel-format correctness; the existing default smoke uses
colored row/column bars and also passes with this exact final binary.

Migration control: default property absent completes save; property enabled
fails with `pre-save failed: bochs-display`; both QEMU processes exit0. Snapshot
migration is deliberately unimplemented, rather than silently dropping state.
No migration restore or native reset qualification is claimed.

At640x480, explicit SPICE60, image compression off, identical atomic token-band
writes,15-second samples at8ms:

| Case | Producer records | Valid samples | Invalid after start | Distinct sampled IDs | Published / replaced |
|---|---:|---:|---:|---:|---:|
| Immutable snapshot + normal32px updates |900|1846|16|900|900 /1|
| Immutable snapshot + one dirty bounding box |900|1863|0|898|899 /2|

An initial token ID0 is installed before the timed producer. It can contribute
to sampled distinct IDs, so these counts are not a claim of901 newly produced
frames or >60 Hz delivery. ACK counters901 include that initial commit; the
producer records IDs1..900. Different pending replacement counts expose real
latest-only dropping. One DISPLAY_MARK in each case is not a per-frame completion
signal. Raw samples, producer times and display invalidations are retained.

A five-second negative control deliberately commits mismatched duplicate tokens
before the intact token, using the same single-bounding-box binary. It retains
556 invalid versus65 valid samples,191 producer records and222 publications.
Thus zero invalids in the intact control is not a decoder that stopped rejecting
torn source tokens. The negative producer is slower because it deliberately
waits20ms; it is a correctness control, not a cadence comparison.

These results support incremental SPICE region application as a remaining
sampled-buffer tearing mechanism in this serialized fixture. They do not prove
all native tearing has the same cause, all frame pixels are atomic in the client,
or that capture source pixels remain stable after the source diagnostic check.

## Build, failed attempts and reproduction

The new isolated source tree copied the pinned352 QEMU10.1.2 source with existing
explicit nongl refresh and Bochs full-refresh patches. The snapshot patch was
applied third. The one-bounding-box patch was built separately fourth. Existing
source/build directories and container images were not modified.

Archive SHA256 `9d75f331c1a5cb9b6eb8fd9f64f563ec2eab346c822cb97f8b35cd82d3f11479`;
use the existing `tools/build-spice-refresh-ab.py` safe extraction function.
Configure flags and Python/Ninja paths are retained in
`run/c369-snapshot/build-receipt.json`; configure/build logs are retained.
Use `ninja -j4 qemu-system-x86_64`, copy each completed binary before changing
patches, and pass the exact source `pc-bios` directory to standalone probes.
The initial configure lacked Ninja in PATH; it was rerun with the existing
research tools. First final-pixel and legacy invocations of a relocated binary
failed before test setup because its BIOS search path was absent. Those logs
remain under`pixels-final` and`legacy-default-final.log`; successful reruns use
explicit `--bios-dir` or the original build binary path. No device exposure
occurred. Earlier pre-counter exploratory results are retained and superseded
by the final rows above.

Example final snapshot correctness invocation:

```sh
python3 -B tools/qemu-snapshot-smoke.py \
  --qemu /home/bogdan/macos-vm/run/c369-snapshot/qemu-snapshot-final \
  --bios-dir /home/bogdan/macos-vm/run/c369-snapshot/qemu-10.1.2/pc-bios \
  --output /home/bogdan/macos-vm/run/c369-snapshot/new-pixel-repeat
```

For the client comparison use `tools/spice-refresh-smoke.py --snapshot --rate 60
--seconds 15` with the respective binary, BIOS directory and a fresh output;
add `--split --seconds 5` for the negative. Existing9 focused build/producer tests
pass; the guest patch applies cleanly but is not compiled or installed.

Next: parent review and compile the separate guest bridge draft, opt-in presenter
ARM only after successful capture startup, and separately pinned QEMU image and
admission contract. Retain one-shot ownership and report synchronous copy cost.
