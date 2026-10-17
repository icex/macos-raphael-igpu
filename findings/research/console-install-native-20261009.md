# Candidate364: existing-user packaged installation and native shutdown wait

Run `bd561e87b688c79cefaa932c5b56274e`, metal-202, MODE2#298,
version1.0.364/build`05847d6e7a254574b30d83649750e407`, runHEAD`b340479`,
buildsource`01a25e7`. Same native driver behavior and full-refreshON/SPICE60/
USB/libvirt profile as361. [Hashed evidence](console-install-native-evidence-20261009.json).

## Existing-user installation

The standalone source ZIP SHA256
`ee248a5732069d493321de13bc21092a37ee640fc76c4b5b38abbccb09a8dbdd`
was downloaded and verified inside macOS. With the console agent active, installation
refused before replacing any of the four targets; before/after identities match.
Bootout is asynchronous: the immediate inspection still showed the exiting agent,
then the actual installer observed it unloaded and all helpers stopped.

The package compiles three helpers with explicitO2 into a private staging app,
signs/verifies and records provenance before publication. Actual macOS installation
and strict signature verification pass. All16 transaction tests also pass on macOS
using disposable owned directories: interrupted publication/recovery, foreign-edit
refusal, exclusive renames, loaded-agent/observer refusal and retained old files.
This is native syscall/logic testing, not a power-loss test of the installed app.

The changed ad-hoc binary initially fails ScreenCaptureKit with TCC-3801. After
its launcher exits, old framebuffer pixels are displayed at an incompatible mode;
the retained screenshot is stale/corrupt output, not proof of corrupt source frames.
Only org.raphaelgpu.console ScreenCapture consent is reset via tccutil. Through the
existing Screen Sharing route, ordinary System Settings authentication/add-app UI
renews consent for the exact installed bundle. No TCC database/policy bypass.
Subsequent live presenter logs confirm capture, not merely an enabled UI checkbox.

Reinstalling the identical package builds an identical complete app and all three
binary hashes. CDHash`e89e4623797593097e9fdb5986c2604a22268dd8` is unchanged.
The agent restarts and copies frames without another consent change. This is an
existing-user same-package reinstall, not fresh-user or next-boot qualification.
Both successful transaction directories and previous files are retained in the guest.
A host export verifies11 evidence files and actual installed hashes against provenance.

## Desktop and audio

The final full screenshot shows the correct Finder desktop/menu/dock in the actual
named virt-manager window after reinstall. Display-awake assertions pass. The
coordinated mouse/keyboard fixture is not rerun;361 remains the input evidence.
During collection host window layout/focus changed; a non-manager screenshot was
rejected and removed, and the final manager capture was explicitly focused and
visually checked. No input/scaling regression is inferred from those observer limits.

Default afplay stereo still passes997.14Hz left/1498.57Hz right, both-channel,
silence and clipping checks. WAV SHA256
`814f758050faa5c526d51d10addfab997883886ecd2de709a6524526fa148cc3`.
Exact host VM stream/client route, volume/mute/defaults and owned module/sink removal
are independently verified. Guest inventory retains the default QEMU USB output.
Endpoint audibility, every application and A/V sync remain separate.

## Capture and shutdown

CORE_PROBE_PASS, earliest_failure=null, genuine guest-shutdown terminal with
process_exited=true. Recovery is recovered/authorizes_launch=true. Viewer closure
first preserves the exact VM lifetime; the cycle is stopped through stop-requested.
Host remains awake; no reboot/rebind.1262 host tests pass,8skip; stage88 pass.

Both native capture hooks record shutdown_event_wait=true, then natural container
exit in about0.411s. The identity-bound guest shutdown event at68440.33893217
precedes critical recv-reset at68440.340182555 and console cleanEOF at
68440.340220815 (about1.25/1.29ms). Reviewed exact staged source permits this wait
only for the original pending zombie with additional tasks and a recent bound
guest-shutdown event; subsequent completion is rechecked. Both end with
completed_original_zombie=false, consistent with eventual reaping. This is the
first native exercise of the event-wait branch after356/358/361 found completed
process state. Initial task IDs are not separately retained, and one success
is not universal crash/worker-delay qualification. Reset and cleanEOF stay distinct.

Next: next-guest-boot consent/helper persistence, source-cadence A/B, clean-user
first-use/bootstrap, robust permission-loss presentation, broader lifecycle/managers
and full desktop/codec/performance roadmap. A working existing-user update does
not complete unattended installation or eliminate the alternate UI needed for consent.
