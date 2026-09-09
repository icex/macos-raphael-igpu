# Candidate 176 recovery/GART range audit

Scope: offline source, artifact, and validator analysis only. No GPU, VFIO,
MMIO, VM, boot, device, ledger, receipt, or existing experiment artifact was
modified. The audited recovery producer is `tools/vfio-recover.py` SHA-256
`8ff51636013da702fed170933ef69f62ae15bbf91d1e59011dc140b9782ee39d`;
the original consumer was `tools/experiment.py` SHA-256
`5834d763ac37c7689083fa83ee87ff3dd862a3c2599385b9d09985df5bf31613`.

## Finding

Candidate 176's active context-0 GART occupies BAR0
`[0x0fdfc000, 0x0fffe008)`. The schema-6 receipt derives that interval from
physical root `0x84fdfc001`, physical framebuffer base `0x840000000`, page
range `0x0ffbfa00..0x0ffffe00`, and size `0x202008` (263,169 eight-byte
entries). The producer's recovery writes are disjoint:

| Purpose | Half-open BAR0 range |
| --- | --- |
| Consumed ACTIVE descriptor | `[0x0f000000, 0x0f000048)` |
| Ring | `[0x0f100000, 0x0f110000)` |
| MQD | `[0x0f110000, 0x0f110800)` |
| RPTR report | `[0x0f111000, 0x0f111004)` |
| WPTR poll | `[0x0f111008, 0x0f111010)` |
| EOP | `[0x0f112000, 0x0f113000)` |
| Completion fence | `[0x0f113000, 0x0f113004)` |

The last host-KIQ byte precedes the GART by `0x0ce8ffc` bytes. The guest's
launch-bound ACTIVE reservation independently proves that both Apple BAR0
allocator sizes were capped at `0x0f000000`, reserving the entire final 16 MiB;
that allocator ownership does not mean recovery overwrote the entire reserved
interval.

The old `_valid_gart` predicate nevertheless rejected every active GART that
intersected `[0x0f100000, 0x10000000)`. An in-memory isolation check against
the unchanged raw receipt returned `['recovery_receipt']`; changing only the
test copy's internally consistent GART offset/root to `0x0e000000` made the
full schema-6 validator return `[]`. This identified `_valid_gart` as the only
failed receipt predicate.

The serial artifact also contains native page-table bytes from the guest. PTE
index `0x4a0` at BAR0 `0x0fdfe500` was `0x0003000413504077` (little-endian
`77 40 50 13 04 00 03 00`), and index `0x3e0` at `0x0fdfdf00` was
`0x00030003f7627077` (little-endian `77 70 62 f7 03 00 03 00`). Both offsets
fall within the receipt's GART extent. These are bounded guest-time reads of
two entries, not a complete post-recovery page-table dump.

## Consumer correction

Schema 5 retains its historical broad exclusion. Schema 6 now excludes two
independently pinned, conservative mutation spans:

- descriptor `[0x0f000000, 0x0f000048)`;
- host-KIQ `[0x0f100000, 0x0f113004)`.

The second span includes the small unwritten holes between KIQ objects and
therefore cannot admit an overlap with any current producer write. Regression
tests compare these consumer pins with the producer's descriptor and
`host_kiq_scratch_ranges()`, exercise both sides of each boundary, accept the
exact candidate-176 GART extent under schema 6, and prove the same extent
remains rejected under schema 5.

After the correction, all three immutable receipt forms validate without
changing their bytes:

| Receipt | SHA-256 | Schema-6 errors |
| --- | --- | --- |
| Coordinator run copy | `77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180` | `[]` |
| Archived run copy | `77b0931dcefe4c710db724d6cedbda22acf42c3c43de2f0aba25546d396ea180` | `[]` |
| Canonical serialization | `4e6c1519f18c0bb60efeb816045eb3aedf6231a0ef8746a530c768996e7e6676` | `[]` |

## Separate producer hardening

`perform_recovery` consumes the reservation at `tools/vfio-recover.py:2358`,
zeroing its 72 bytes before `quiesce_gc` reaches the runtime GART derivation
and scratch-overlap check. A hypothetical GART overlapping the descriptor
could therefore be damaged before rejection. Candidate 176 is unaffected: its
GART starts at `0x0fdfc000`. A later producer change should derive the live
GART and reject overlap with the descriptor before consuming it; that ordering
change is outside this consumer-only correction and requires its own
fake-transport ordering test before implementation.
