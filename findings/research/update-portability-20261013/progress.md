# Dynamic update portability — work in progress, 2026-10-13

Candidate485 starts from dev 72a2534. No GPU experiment has run with it yet.

The live GPU-less guest reports macOS **15.8.1, 24H32**, boot
7A7C037F-EFCC-49CF-9DAC-5D61DC06F200, uid 0. This corrects the prior handoff's
15.7 label. The live guest's System/Boot KC SHA256 values match the extracted
24H32 collections (2296155f1f12471e7b774020ba70d9fb487d02224c1f85d373130511969c2243,
cd013c14a7f21dbb8181fb06c44e079de8646b6a674abe21f6e47f42e8979af3).

## Implemented, still awaiting hardware

- All 157 audited kernel image-address sites now resolve before the image's first
  patch. Named symbols use relocation-masked instruction contracts; anonymous
  display-core functions and the PSP firmware-ID table require unique matches
  restricted to executable/constant sections. Catalog references are stable keys,
  never offsets added to the running kext base.
- `kernel-sites.py` independently checks a fileset KC and regenerates the compiled
  catalog. Both real 24G830 and 24H32 inputs pass discovery (314 site checks). The
  archived offline results separately report global ambiguity; named-symbol
  resolution is necessary for several repeated native methods.
- Metal and video driver discovery no longer uses a UUID/address allowlist in the
  deployed current-task COW path. Long surrounding instruction contracts locate
  the six active Metal/VCN sites. The texture flag's bit is derived from the
  image's named AMD_DeviceSettings metadata. Current bytes are revalidated before
  COW, and current mapping protections are restored on every attempted write.
- The active Metal UUID changed from 906f11a39daf35bdb8eacfd2160fae1a to
  5f3475642f8d3a49a50c5220b43f5ceb; VADriver2 changed from
  81df721543e23ba1be2defb1c508b81a to 662187e49f38375b9bf6ccac3f60979a.
  Live text dumps are in ~/macos-vm/run/upload/24H32-*-TEXT.bin.
- Production userspace locator tests pass on both versions' real Metal/VA images,
  including pristine, already-patched, and changed-contract refusal. Synthetic
  checks exercise moved code across a streaming-read boundary, metadata bit
  changes, missing metadata, and ambiguity. This is discovery evidence, not
  acceleration or codec evidence.
- `experiment.py` requires a disk-bound GPU-less compatibility proof instead of
  accepting the saved 24G830 label. `guest-compatibility.py` validates both current
  image artifacts and production locators. Automatic nonce-bound uploads and proof refresh/startup are implemented.
  The first live capture produced an unsealed observation; the launch gate
  rejects it until the identified plain guest exits cleanly and the disk proof
  is sealed. cycle.py refreshes missing/stale proof before MODE2/VFIO exposure.

## Verification and next steps

Latest full host suite: 1615 tests, eight skipped, pass (candidate-485-host-tests-5.log).
Dynamic kext cross-build passes (candidate-485-dynamic-build.log); it must be rebuilt
from a committed tree before staging. Current COW paths must be hardware-tested.

The plain VM runs in rgpu-compat-plain.service, with no VFIO device. Its command
relay/upload HTTP services are owned by this task. An exact-CID deadline timer
limits this plain session to 6000 seconds from its original start. The guest is fetching the
26.7.1/25G241 Tahoe installer via launchd job org.raphael.compat.fetch-tahoe;
check /var/tmp/rgpu-tahoe-installer.log and .err before shutting down. A failed
nohup attempt preceded the launchd job and is not a completed download.

Next: finish automatic fresh compatibility inspection, authenticate the probe
and artifacts, cleanly stop the plain guest, seal its stopped-disk proof, rebuild
candidate485, and run through cycle.py with a 6000-second cap. The current boot's
latest recovery receipt is authorizing, but recheck it and every live safety gate.
Then qualify desktop/managed texture/capture/recovery on 24H32 and separate Tahoe
installation/updates. Do not claim arbitrary future ABI support from byte matches.
No dev/main push has occurred in this task; delivery requires docs, dev integration,
normal push and exact-commit hosted CI.

Update: the host ipsw downloader fetched and verified the 26.7.1/25G241
InstallAssistant.pkg in run/tahoe-installer-25G241/macOS_Tahoe_26.7.1_25G241/.
The slower guest launchd fetch is being stopped; do not count it as completed.
The deprecated rgpunotexxor boot argument now aliases dynamic current-task COW.
Kernel compatibility configuration permits Darwin 25, with discovery still mandatory.

Fresh inspection/shutdown now succeeded end to end: observation
`a1614cea900545de8a8c349d3000f1a7`, plain container c01fecd5115d3546131e1c2b01d7433043d5b5379eeca09a05c1e708cb02c284,
guest boot 293C8C48-DE6F-45B6-B218-3D96FB329932. Guest acknowledged the
identity-bound native shutdown before requesting poweroff, and exact-CID Docker
exit was 0. `run/guest-identity.json` contains the sealed stopped-disk proof.
The first shutdown lost its relay reply and produced no sealed proof; a grouped,
nonce-bound pre-shutdown acknowledgement fixed this race, followed by a fresh
plain boot and complete recapture. Original failed observations remain.
