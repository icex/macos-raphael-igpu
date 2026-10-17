# Critical record overflow — 2026-09-16

Run279/3f5d8049506b1164b29292988b0eacb5 stopped on definitive capture loss.
The final complete512-record snapshot reports8drops. A read-only inventory validates
individual chunk CRCs before decoding records for diagnosis; it is not a recovery
proof and does not override the strict parser.

Of the512retained records:44 VCNDPM image lookups,35 successful FBEXPAND COW records,
32 raw VCNQ packet records. The lookup path can repeat for every process or hardware
query; successful patch records grow with process creation. These additions exhausted
the older finite trace budget. The buffer and loss checks behaved as designed.
Inventory: candidate-279-results/critical-record-inventory.json.

Candidate280 retains all hardware behavior from279. It moves routine image lookups
and raw packet dumps to ordinary serial; found-but-invalid image identities remain
critical. The existing atomic SuccessRecordBudget retains the first four successful
COW records per Metal/video family in critical capture and all failures. Every
success still reaches ordinary serial. Required route, build identity, queue result,
VM fault, ownership, lifetime, shutdown and recovery records are unchanged. No buffer
capacity, parser tolerance or load-bearing design contract changes.

Regression coverage exercises1000successes per COW family followed by failures and
lifecycle records after400earlier critical records:413retained,0drops, faults and
final lifecycle record readable. This verifies the budget primitive; hardware
qualification must still demonstrate no critical drops and successful cleanup.

## Hardware validation — candidate280

Run4eeb58b45c54db193ec9b14421f23f33, build51bfd732cf824249b70981f0c36fe314,
host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, MODE2#156. Four independently
seeded feedback processes (two sequential, two concurrent) pass48cases and
5,280,000checked pixels; fresh foreground native-panel RFB captures0/2 are clean.
Hardware H.264 and HEVC each encode/decode120unique frames with maxlumaerror1/0.
PerfPowerServices remains0.0% CPU/0.77s cumulative.

Final acknowledged critical snapshot18 has398records, zero loss. Guest exits after
requested shutdown. Schema6 recovery authorizes launch with CP_STAT=0, active_after=0,
forced_inactive=0. Overall CORE_PROBE_PASS. Host938tests OK,3skipped.
This closes overflow for the tested workload; it does not prove unlimited diagnostic
capacity, full desktop correctness, resource reclamation or independent-host-boot
recovery. Earlier lossy runs remain INVALID. [Artifact hashes](candidate-280-qualification-20260916.json).
