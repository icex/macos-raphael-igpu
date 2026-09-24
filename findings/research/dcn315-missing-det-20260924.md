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
