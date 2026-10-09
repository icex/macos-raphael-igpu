# Live status — 2026-10-09

## Candidate390: installed native-scale console resize and 4K selection work

Run `3d0e4869c7f1c49af50497f440996a5b`, metal215,1.0.390,MODE2#311,
bootba51b3c6. Sourcee147551,launch07d79d0,buildc1591507f28f48e7a42b8ce3e92f6c51;
executable7bbd044587498bae26e1daf182a36c9d2147ddfb59c99e9108dd80128d48dad9.
External support adds fixed per-holder1x/2x preference and EOF-framed v2 control.
Initial1x4K selection failed because public mode enumeration filtered modes larger
than the first/native entry. Read-only raw inventory and decoded SkyLight support
this diagnosis. Installed support from3914826f69 orders the existing largest mode
first; public3840x2160 physical/logical selection and startup now pass. No private
mode mutation ran. Final payload5ed647ae17f902d25daf30021a29b50e64e2f27660dc85d8d84c668dd3697633;
holder2970,agent3023,presenter3024. Capture app/receipt/signature unchanged.

Actual manager automatic1x viewports1235x743,1237x745,1441x961,1235x743 settle to
matching surfaces. Five-target input/exactkeyboardtoken passes with0misses and
0geometrychanges. Stereo48kHz997/1498 sample capture and independent route/volume/
mute/defaults/module restoration pass. Endpoint audibility/A-Vsync unqualified.
Fragmented v2 request passes; malformed suffix,no-EOF and policy mismatch controls
refuse without mode mutation. Owned2x restart supports legacy2000x1000 physical /
1000x500 logical; odd2x client refusal and mismatched1x status2 preservegeometry.
Owned1x restart restores4Kstartup. Preference preserved across support reinstall;
freshguestboot persistence of this newpolicy remains next.

Ordinary presenter,snapshotUNARMED:110s mixedsource completes6600draws. Actual
1440x900/GDK1 manager observer completes100.006s,5795distinct+1duplicate valid
samples,13startupinvalid and0poststartupinvalid. Firstfive localized/fullfield
phases measure57.9–58.0 distinct intervals/s; final10ssourcephase unobserved.
Normaldesktop returns and screenshot inspected. This is token sampling, not
fullframe integrity, universal60Hz, absolute latency or scanout qualification.

Guest-requestshutdown passes; private terminalguest-shutdown/process_exitedtrue.
Docker die0/destroy, no containerkill/stop. Bothcapturehooks natural-container-exit,
~0.433s,no shutdown-eventwait/zombie;consoleEOF,criticalRST. Terminal-prefix
snapshot18(367records) accepted, but replay retains1corruptline and incomplete
snapshot14(896chunks,noend). Recoveryrecovered/authorizes_launch=true. Host remains
awake,vfio-pci,power/control=on. Serial retains8largeallocationfailures(size60293120,
free77–81MB,fixedfree1883172864); relationship to tested behavior unlocalized.
Do not claim error-free capture or driver operation.

Evidence: run/candidate-390-results; c390-v2-four-k.txt; c390-native-framing-results.txt;
c390-v2-auto-manager-events.jsonl;c390-input-v2-final.txt;c390-v2-audio-result.txt;
c390-v2-audio-restored-independent.json;c390-scale2-check.txt;c390-scale1-restore.txt;
c390-matched-1x-analysis.json;c390-matched1x-source.txt;c390-matched1x-presenter.txt;
c390-post-workload-desktop.png;c390-final-state.txt;c390-final-seal.txt;
c390-viewer-close-alive.json;c390-docker-events.jsonl. Functional/report manifests
are in candidate391 and will be merged for delivery. Full pre390suite1442/8skip
passed. Delivered devc8fc5d5 remains hostedtest/build green(run37975249900),mainunchanged.

Next:392 freshguestboot installedscale1 persistence/4K, reconnect and stationary
pointer resize, then milestone docs/testedbinary/hostsuite/dev+exacthostedCI.
Investigate retainedallocation failures; sustained/fullframe performance,
crash/forced-stop/independenthostboots and othermanagers/VirtualBox remain open.
