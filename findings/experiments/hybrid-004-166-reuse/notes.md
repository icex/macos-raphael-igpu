# Hybrid-004: candidate 166 on a rootlessly recovered GPU

This is the second GPU launch on host boot `851d35df-7e63-4154-b70b-5cfa044913d6`.
The coordinator consumed recovery `748b4f99cc1b4d029fbce560b6cbeb4f`, created after the
candidate-165 panic. This is the first direct proof that the rootless PSP teardown is sufficient
for the Apple stack to initialize again without a host reboot.

Candidate 166 applied the one-instance topology repair and repeatedly mapped higher-layer engine
2 channel requests to the real engine 1 object. GC/SDMA hybrid creation returned status 0,
`initializeHWEngines`, the retained SDMA0 start, `startHWEngines` and `powerUpHW` all returned
success. KIQ stamps advanced through at least stamp 21, with no host fault.

The original verdict was `INCONCLUSIVE`: a complete structured snapshot covered sequences 0–62,
then later direct serial records had serial line numbers 2918/2919/10118/10148. The classifier
incorrectly spliced those unsequenced line numbers into the structured sequence and called the
gaps capture loss. Reclassification after keeping a complete structured prefix separate is
`PROBE_NOT_RUN`. This is an observation bug, not missing native evidence. Because the coordinator
saw the false capture loss during the live run, it correctly withheld the Metal probe.

The guest command channel never became reachable before shutdown, so cleanup recorded a confirmed
forced stop. Post-stop rootless recovery again completed both PSP destroys (7 and 1 polls), kept
PCI command `0x0003`, and saw no host fault. Its single-use receipt authorizes one final launch on
this boot.
