# Candidate368: intact capture-source tokens with downstream partial tokens

Run177c406a3d3e1c39bdf5327649c5dbd7, metal-204, version1.0.368,
buildb0d4f6d56caa4d23a0aa439e0613aa83, build sourced995a14,
runHEAD0284410f2a14bfd393899bd43090e81ab34b48ac; MODE2#300, bootba51b3c6.

## Native installation and controls

Transactional source package dd10eebe8960b10419f7a968e30c5a526662c71b5323fe8ab253f84d861cb6d9
was packaged from clean88b63c2. Header and presenter source match the run tree;
later merge changed delivery docs/bin only. Appleclang17/SDK15.5 native compilation,
strict ad-hoc signing and installation succeeded. Presenter executable is
3c9c9f78e3602576f280c085115881c10e7d3d3a33dbcb18473a3c6c49a3fa73.
Changed signature first caused TCC-3801. Normal Screen Recording Settings renewal
restored capture; no TCC database/policy edits. An old permission prompt remained
after capture worked; opening its Settings action dismissed it without revoking
permission. Final actual-manager screenshot shows the desktop with no prompt.

Each case temporarily adds only its fresh nonce to the installed LaunchAgent,
restarts the presenter, verifies fresh capture, sets native/HiDPI geometry, and
runs the exact previously compiled bounded prerendered fixture. The same current
QEMU full-refresh ON/SPICE60/USB/private-libvirt profile and manager ROI observer
are retained. Native fixture executable2140622c3a79c95d55b290e56d321dd05006822370044358f0e4daa386e3bb47.
The manager starts before the fixture, observes20s after its first valid token;
source diagnostic observes30s from its first valid token. Fixture ends after60s.
No overlapping guest relays or heavy host jobs during either measurement.

## Observed source versus manager

| Case | Source nonce | Valid / processed source | Source unique / duplicate | Manager invalid / bracketed samples |
|---|---|---:|---:|---:|
| 1080 HiDPI | 7610c8f835e0d38d | 1742 / 1742 | 1740 / 2 | 633 / 1065 |
| Native1080 | e3464c8b0533a68f | 1738 / 1738 | 1738 / 0 | 35 / 1116 |

Both actual readonly-locked SCK source windows complete exactly30s with zero
invalid/unavailable/backward samples, expected scale2/1, firstID1 and lastID1800.
Counters reconcile; these IDs occur in the fixture DRAW logs. Source checker total
cost14.002/8.069ms and maximum0.063/0.018ms include waiting checks as well as the
measurement window; they are not isolated application performance measurements.

Manager invalid samples have no trustworthy sequence ID. Analysis brackets their
host timestamps between valid IDs well inside the source range (120-ID margins),
rather than assigning corrupted IDs a position. It retains all invalid samples
inside that interval. Guest/host clocks are not synchronized. HiDPI errors are
631 CRC and2 torn-cell failures; detailed native errors and raw samples are retained.
This is evidence that tokens are intact at the source-check boundary while partial
tokens appear downstream. It narrows investigation to copying/framebuffer/QEMU/SPICE
and their buffer lifetime/ownership, without identifying one stage. It does not
prove full-frame atomicity, every upstream frame, source stability after checking,
60Hz presentation, scanout or GPU FPS. Busy-dropped and uncaptured frames are excluded.

## Restoration, capture and cleanup

Both case controllers restore the exact original LaunchAgent bytes (SHA
b1cc2d31065b3d5722782d8720029c3f0bbfd776239eb190c3a1c1ecbb858e82), with
diagnostic nonce absent and fresh ordinary capture. Display-awake assertions pass;
final correct desktop seen in actual virt-manager. Input/audio not rerun.
Closing the owned viewer leaves the exact original VM alive.

CORE_PROBE_PASS, earliest_failure=null. Harness stop produces the genuine private
guest-shutdown/process_exited terminal. Both capture hooks defer and finish with
natural-container-exit~0.415s, shutdown_event_wait=false, completed_original_zombie=false.
Critical recv-reset is distinct from console cleanEOF. Recovery recovered and
 authorizes_launch=true. VM/cycle stopped; host sleep:idle blocker stays active.
1268 host tests passed,8skip before exposure; exact build/card/dry-run checks passed.

Next is an isolated, explicitly committed framebuffer snapshot experiment, with
exclusive staging memory, immutable QEMU-owned snapshot lifetime and acknowledged
reuse. Shared guest framebuffer reads and split SPICE updates remain separate
hypotheses. Software overwrite-after-ACK controls precede native exposure.
[Artifact hashes](console-source-token-native-evidence-20261009.json).
