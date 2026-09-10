# COM2 tiny-guest transport qualification

Date: 2026-09-10

## Verdict

The CPU-only tiny-guest qualification passed all 10 cases against the real
`tools/sercat.py` collectors and `tools/vm-supervision.py` supervisor. This
establishes isolation, byte preservation, exact-CID failure handling and cleanup
for the tested QEMU TCG transport. It does not authorize a macOS launch, GPU
access, staging, recovery, or candidate reuse.

The repository launcher source has the planned explicit COM1/COM2 topology, but
it was deliberately not invoked because it launches the macOS VM and requires
host devices. Deployment to `/home/bogdan/macos-vm/macos-vm.sh` remains a later
reviewed step. The production end-to-end gate is therefore limited to source
argument tests plus the equivalent explicit topology exercised here.

## Reproduction and durable result

Run from `/home/bogdan/src/macos-raphael-igpu`:

```text
python3 tests/qualify_critical_transport.py
```

Final output (this report is the durable qualification log):

```text
test_either_collector_loss_stops_exact_cid ... ok
test_forced_close_preserves_only_an_admissible_open_attempt ... ok
test_maximum_fixture_uses_unchanged_formatter_and_parser ... ok
test_missing_either_socket_hits_shared_deadline_and_stops_exact_cid ... ok
test_real_dual_collectors_and_supervisor_capture_isolated_channels ... ok
test_source_built_guest_fixture_is_present ... ok
test_stale_ready_files_cannot_satisfy_new_arm ... ok
test_swapped_channel_tokens_refuse_verify_and_stop_exact_cid ... ok
test_swapped_socket_paths_fail_producer_capture_acceptance ... ok
test_swapped_uart_indices_fail_producer_capture_acceptance ... ok

Ran 10 tests in 131.582s
OK
maximum CR2 fixture: 1144917 bytes; 99.385s nominal wire time;
sha256 83be7814817571a62e58879602b051615940d4bf6b840ae38cdecfa88eedafa5
```

The gate source-builds a Multiboot ELF in a unique temporary directory using
the installed compiler, linker and `objcopy`. It commits no guest binary. The
host generator directly includes unchanged `src/CriticalReplay.hpp`, emits a
one-record complete baseline followed by the cumulative maximum of 512 records
at 511 printable bytes each, and sends that byte stream as the guest payload.
The guest emits the exact producer line
`RGPU_UART_READY v=1 b=0123456789abcdef0123456789abcdef port=2` before CR2.

Every QEMU instance ran in the pinned local image
`sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`
with an explicit QEMU entrypoint, `-accel tcg`, `-nodefaults`, `-vga none`,
`-display none`, `-net none`, no Docker network, no passed devices, and no
KVM, DRI, VFIO, macOS disk or host graphics adapter. QEMU started paused. The
test obtained its real full Docker CID, armed both real user-systemd collectors,
verified `<CID> console` and `<CID> critical`, then continued the guest through
QMP. COM1 carried 1.2 MB of deliberately malformed/interleaved CR2-like console
noise while COM2 remained byte-identical to the formatter output and passed the
unchanged `tools/critical-replay.py` parser.

Three forced closes occurred after the baseline END and at distinct offsets in
the maximum attempt. Strict parsing refused each truncated capture; the existing
open-attempt rule accepted only snapshot `0x01020303` plus the observed open
attempt, and no maximum-snapshot END was present. Stopping either real collector
stopped its exact Docker CID. Missing either socket independently reached the one
shared 60-second readiness deadline and stopped the exact CID. Swapped UART
indices and swapped socket paths failed producer/capture acceptance; a swapped
channel token failed real supervisor verification and stopped the exact CID.
Stale ready files were removed and replaced with current exact tokens.

After the final run, Docker listed no `rgpu-com2-qualification-*` container,
user systemd listed no full-CID qualification collector unit, `/tmp` contained no
`rgpu-com2-*` directory, and `tests/fixtures` contained only the two source files.
Residual socket paths, when present before temporary-directory removal, refused
connection and owned no listener.

## Wire-time consequence

The maximum payload is 1,144,917 bytes including its baseline snapshot. At
115200 baud with 8-N-1 framing, the theoretical minimum is 99.385 seconds before
polling and scheduling margin. QEMU's emulated UART completed in about one second,
which is useful for isolation testing but does not change the physical rate. A
driver total-snapshot deadline that promises the absolute maximum fixture must
therefore exceed 99.385 seconds with explicit margin, or the accepted production
record/wire bound must be reduced. The host exposure limit must not be extended
to hide this constraint.

## Independent host-source review

Focused host and historical tests passed:

```text
python3 -m unittest tests.test_sercat tests.test_vm_supervision \
  tests.test_experiment tests.test_classify_run tests.test_stage_candidate
Ran 198 tests in 8.187s -- OK
```

`py_compile`, `bash -n` and `git diff --check` also passed for the reviewed
transport, collector, supervisor, experiment, classifier, staging, launcher,
redeploy and qualification files.

The initial review found that `tools/classify-run.py::parse_manifest_files`
selected `critical.txt` without validating the producer-ready line. The host
implementation agent fixed it to use the shared `producer_ready_state` contract.
The re-review verified that missing readiness adds pending capture loss, wrong or
duplicate readiness adds definitive capture loss, and one exact build-bound line
adds no loss. The focused classifier/experiment regression passed 162 tests.

The design also asks the narrow COM1 merge to retain shutdown evidence and reject
conflicting run identity across captures. Current `parse_console_lifecycle`
retains guest panic and rejects a conflicting driver build. The existing console
wire parser has no explicit shutdown or run-identity record to merge, so this is
a plan/wire-contract refinement rather than an invented parser requirement. The
coordinator should define the exact existing console evidence, if any, before
expanding that parser.

## Identities

```text
c72e6187899b89c0cebb4d2d7ffefc0008c32483abf9f86021d227fc72ba7a0e  tests/fixtures/com2-guest.c
20ac6dec54177ce319d21efb12d7e9f0ad0af2af697a146a7509bf4269e14b8b  tests/fixtures/com2-guest.ld
97f10e053f427a795c75bcfb4e61cc0ededd169776fd0af4eb8c3f82d3493521  tests/qualify_critical_transport.py
87cb7aac27fb67334292beaa47a1a90d1fec2c7d36070d1b6fa72b9fecf4fa4c  tools/critical-transport.py
9d386cd3081e3b08dfb1354cb2645609b73840b488d485a4ce2df3a6d7bb759e  tools/sercat.py
2ececbc3e8efe608497fb1565ff0556fadbc83c1602c63f4e3cb7ed7d9666064  tools/vm-supervision.py
053599f53696645432defee93a4809de572d7ca87369de75fc83eb041acc3ba8  tools/experiment.py
ff4a754d5d4a109f90710de93336481a8aa1f1a1fcb23888afa28ced5255fdfb  tools/classify-run.py
96ad8312748ef2408859ba23d991da0b6766d3774595e4f85c638ddbb78206f7  tools/stage-candidate.py
d7da2c608ea00a3969df2426770a069ffbbe4d701ce0c9f695e28bff5b9a1903  tools/macos-vm.sh
98c6d958111f6a0684b3299f220bd031330810d59bb1a4fb59231e4cabbe4570  tools/redeploy.sh
8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61  tools/critical-replay.py
6f43686e00766d468326dfd018a97861e892686c8259d122e4a115d344e965ba  src/CriticalReplay.hpp
```
