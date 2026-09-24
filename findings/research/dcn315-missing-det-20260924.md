# Missing DCN315 detile allocation

## Candidate319 retry: missing live DET allocation confirmed

Run4d173834d3c6b91425d008e9bc5743eb, MODE2#247, source5131613,
metal167. Native1920x1080 pixels/logical60Hz, awake assertions verified.
DET0-3 requested/current=0; COMPBUF requested/current=13 segments. DPG0=0,
HUBP0 timeout2/underflow1, surface-in-use0. No new physical-screen observation;
this confirms missing allocation during active native scanout, not its causality.
Core probe passed, complete capture, finalCORE_PROBE_PASS. Harness stop-requested,
exited-after-guest-request, recovered/authorizes_launch=true. Next320 allocates
three unused64KiB segments to DET0 with bounds/stability guards.
Evidence: run/c319-fetch-scanout.json, c319-awake-check.txt, c319-awake-60hz.txt,
and candidate-319-attempt-fetch-results receipts. Prior early panic remains archived.

Linux dcn31_hubbub.c program_det_size uses64KiB segments; dcn315_resource.c
single RGB plane selects192KiB. dcn31_fpu.c dcn3_15_ip declares1024KiB total.
DCN3.0.2 register headers lack DET0-3/COMPBUF controls; Apple targets that generation.
Candidate320 writes only DET0 request=3 before OPP0 video-mode write, checks current
size with bounded30ms poll, and preserves COMPBUF13. Reject any existing DET,
transitioning/oversized COMPBUF, inaccessible read or config error. Default off.
The hypothesis is falsified as sufficient if allocation applies but fetch remains stuck.
Visible318 test pattern bypasses this buffer and therefore does not qualify desktop.

## Candidate320 active observation

Run309ef9a1e0b27ae7f7fab0b73f04ea45, MODE2#248, build2b5618317a2541f9829fbd45bdae89a4,
source9b5503b. First bounded poll ended with request3/current0; later live read
confirms DET0=0x303. After verified-awake native1080p60, HUBP0 timeout/underflow
are clear, FLIP_PENDING=0, and EARLIEST_INUSE matches requested addressf412cc0000.
OTG pixel readback is nonzero. Physical picture observation is pending.

Correction: SURFACE_INUSE=0 alone does not establish a stuck fetch. Linux
hubp2_is_flip_pending uses FLIP_PENDING plus SURFACE_EARLIEST_INUSE compared with
the requested address. The earlier319 timeout/pending evidence remains valid;
320 clears both. Do not equate nonzero OTG pixels with correct physical desktop.

Active artifacts: run/c320-det-scanout.json/txt, c320-awake-check.txt,
c320-awake-60hz.txt. Final capture/shutdown/recovery are not yet available.
