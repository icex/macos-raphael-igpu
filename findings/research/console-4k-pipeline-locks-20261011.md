# Candidate 444: full-field 4K window delivery from ~40 to ~50 IDs/s

Only full-field 4K performance is active. Host viewer stayed a normal 1440x900 window (GDK1,
X11), no fullscreen, input grabs or automatic USB. Host awake blocker retained. Same boot
`ba51b3c6…`, build `245bdd63d44749ad908125b57e216c88` (1.0.444, card metal-238), GPU source
`d1deade…` unchanged; guest presenter unchanged.

## 1. Loss budget (443 attempt budget-d)

443 run `b056c43988e9507beb3f6d7306cc5809` repeated the coordinated GL window (439 image, default
pacing) and also captured the guest presenter log and QEMU `bochs-snapshot-timing` windows on the
host monotonic clock. Full-field, per second: ScreenCaptureKit ~58 complete frames → presenter
copies/commits 44.1-45.9 (drops ~12) → QEMU replaced 2.2-3.8 before publication → published
≈ dequeued ≈ client 42.0. The presenter keeps one frame in flight; its full-field worker rose to
~15.6 ms because the snapshot commit (3.7 → 7.5 ms) waited for QEMU's global lock behind SPICE
update creation (~4.9 ms). QEMU's copy itself was ~3.3 ms.

That session also tried the host Moonlight Flatpak through the documented relay: the guest
Sunshine answered with the paired identity but trusts only the user's MBP and iPad, so the host
client was refused ("not paired"). Moonlight measurement is deferred by the user. With seven
slirp host forwards and the relay added, its strict shutdown classification was
`capture-abort-after-request` (guest exit observed, QEMU still exiting when captures ended,
`original-pid-present`); recovery authorized reuse. All 444 runs without forwards were clean.

## 2. Server arms (same card, pins, MODE2 342-345)

| Cycle | Image | Change | Run |
|---|---|---|---|
| a | 439 `085d8ac…` | baseline | `b497f2d0201925ebc067c56d5640146d` |
| b | `dade0cb…` | snapshot copy without the global lock | `a3c8ce8bc1ce91cd4329e2ab63288fa0` |
| c | `6a2165a…` | b + publish each placed snapshot from a main-loop bottom half | `d2572b4f776184f35b3f255837c9ac56` |
| d | `a18ff5a…` | c + SPICE update diff/copy without the global lock (display lock held) | `ac0c365f40e164da7063307d5702be68` |

Patches: `patches/qemu-10.1.2-bochs-snapshot-unlocked-copy.patch`,
`qemu-10.1.2-bochs-snapshot-commit-publish.patch`, `qemu-10.1.2-spice-create-unlocked.patch`
(cumulative, on the 437 source verified identical to the 439 binary).

Full-field phases (two per window), client unique decoded IDs/s · server dequeues/s; localized range:

| Window | Server | Client | Full-field IDs · dequeues | Localized |
|---|---|---|---|---|
| a | 439 | 441 | 38.71/39.09 · 38.71/39.31 | 55.9-56.6 |
| b | unlocked copy | 441 | 40.09/39.51 · 40.37/41.24 | 53.1-55.6 |
| c | + publish | 441 | 38.84/39.25 · 38.90/39.30 | 57.7-57.9 |
| d | + create unlocked | 441 | 39.29/40.31 · 53.11/53.61 | 57.9-58.0 |
| d repeat (f) | same VM | 441 | 41.35/41.62 · 52.09/52.09 | 57.2-57.3 |
| d LZ4 (e) | same VM | 441, LZ4 requested | 34.31/35.46 · 53.24/51.38 | 57.4-58.0 |
| **d (4)** | same VM | **444 zero-copy receive** | **50.35/49.79 · 52.47/52.18** | 57.3 |

- b: commits rose (40.6 → 45.5/s, commit 7.4 → 6.4 ms) but the refresh timer now often ran just
  before a copy finished, so more snapshots were replaced (localized fell). Holding the lock had
  been synchronising publication to commits.
- c: publish-on-commit made QEMU lossless (0 replaced; localized = commits ≈ 57.8/s), but the
  immediate update creation now held the lock right after each commit, so the next commit waited
  (8.9 ms) and full-field commits fell to ~39/s.
- d: with update creation outside the global lock, full-field commits reached 53.1-53.7/s and the
  server dequeued all of them (presenter drops ~6/s). Client IDs stayed ~40: the display channel
  carried ~1.3 GB/s (~40 full raw updates/s) and the viewer's main thread was 90-91% busy.
- LZ4 lowered bytes but cost more than it saved (34-35 IDs/s). Raw stays.

In arm D's QEMU, `pending_present` in the timing windows overcounts replacements for b (sampled
before the unlocked copy); c and d sample after re-locking. Timing windows stop after 128, so the
later same-VM windows report dequeues rather than commits.

## 3. Client: zero-copy raw receive

Profile of the viewer main thread (full-field, arm D): ~19% pixman blit of the raw image into the
CPU primary, ~17% Mesa texture upload, and ~34% libc copies, mainly `spice_bitmap_to_pixman`
converting each 33 MB raw bitmap into a temporary image first. Large messages also arrive in a
fresh `mmap` per frame (above glibc's 32 MB threshold).

`patches/spice-gtk-0.42-raw-zero-copy-receive.patch` on the 441 raw-primary client:
uncached, single-chunk, top-down 32-bit raw bitmaps matching the canvas format are wrapped in
place instead of converted; large (≥1 MB) messages reuse one receive buffer, shifted 0-3 bytes
from the observed pixel misalignment so later frames land 4-byte aligned (the first frame showed
data at an odd address and is copied as before). Format metadata is registered without owned
data. Result (window 4): full-field 50.35/49.79 IDs/s at 52.2-52.5 dequeues/s, viewer thread
79% (was 90-91%), 0 duplicates, 9 startup-invalid samples (baseline 10).

Moving GL output with this client (window 3, same VM): 100/100 sampled FBO readbacks valid,
0 missing, 100 distinct strictly increasing sequences; primary 3840x2160, FBO 1440x900,
content 1440x810 at y=45.

One viewer (window 7, the earlier non-engaging build, profiled with DWARF unwinding) crashed
with a garbage PC 24 s after profiling ended; the same build completed window 8 unprofiled, and
the final build completed windows 3 and 4. Recorded, not explained.

## Status

Combined arm D server + zero-copy client is the best measured windowed path: ~50 full-field and
~57 localized decoded IDs/s at 4K → 1440x900. Not established: sustained 60, displayed-frame
FPS, every-frame integrity, input/cursor/resize/fallback with these changes, or safety of the
unlocked paths beyond these runs. QEMU arms are research images selected by pins, the client is
a private build; nothing is installed system-wide.

## Next

1. Presenter: overlap the ScreenCaptureKit buffer lock with the previous copy/commit (two in
   flight), now that commits take ~5 ms; needs a presenter rebuild and one Screen Recording
   consent renewal in the guest (ideally signed with a stable identity so later rebuilds keep it).
2. Client: remaining primary blit + texture upload (one CPU copy + one upload per frame).
3. Moonlight: pair the host client (PIN in Sunshine web UI) or measure from the user's paired
   devices; the September configuration (ScreenCaptureKit Sunshine, VCN preset, 2 GB UMA) is
   installed and running in the guest.

Evidence: [console-4k-pipeline-locks-evidence-20261011.json](console-4k-pipeline-locks-evidence-20261011.json);
`~/macos-vm/run/c443-d-*`, `c444-*`, `candidate-444*-results/`; operator files in the candidate-444
`.research/` (driver `c444-drive.py`, budget `c444-budget.py`, thread sampler, QEMU and client trees).
