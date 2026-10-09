# Live status —2026-10-10

## Candidate401: true VirtualBox desktop/input, software-only singleCPU

BootC UUID1a0740c7-3655-481e-a5f5-e7dac76dee1e reaches actualmacOS desktop;
rootviewed Terminal VBOX401_INPUT_OK, hw.ncpu1/build24G830/awake assertions.
SamebootBloader, only8→1vCPU; actualTSCstillVirtTSCEmulated4294967295Hz.
No monotonicpanic through~238s; SMPcontribution supported, rootcause notproved.
NoRaphael/VFIO/Metal acceleration or sustaineddesktop performance qualification.

Cleanup was NOTnatural: sudo-n shutdownrefused; ACPIconfirmation thenTerminal
backgroundcaffeinate confirmation blockedshutdown. Controllerdeadlinepoweroff
~237.8s; immediateunregister GUIlocked(originalcleanup_error retained).
Rootlater verifiedexactUUID/configpoweredoff, unregistersuccess,listabsent;
root-cleanup-reconciliation.json explicitlypreserves originalresult. SoftwareVM
stopped/unregistered, not a guestshutdown or GPUrecovery pass.

Evidence findings/research/virtualbox-single-cpu-native-20261010.md +16hashes.
Next403 sourceauditSMPclock beforepatch; boundedunregister unlockretry and
stop/disown onlyownedawakejob before graphicalshutdown. Root owns launches.

## Candidate399: accelerated-console timing result

QEMU run1849f3959a4a38e15836c9364554f76f ended with verified privateguest
shutdown/process-exited, Docker0/noKill and authorizing GPUrecovery. Capture
receipts say container-stopped-during-shutdown-wait/deferred/eventwaittrue;
CR2snapshot18/365 records has0corrupt/0incomplete underterminal-prefix tolerance.
4K manager4036unique/100.006s,0invalid/duplicates; shortphase5 excluded.
Host snapshotcopy6.834ms includingfirsttouch dominatesallocation0.02058ms and
pending-free0.09521ms; guestdoorbell6.983ms. Nooptimizationgain is claimed.
The latec399-desktop.png was the wronghostwindow and is excluded fromvisualproof.

Both399GPUcycle and401softwareVM are stopped; noactiveVM is implied by this
integration status. Root owns future launches. Source/evidence reports remain
findings/research/console-host-snapshot-timing-native-20261010.md and
findings/research/virtualbox-single-cpu-native-20261010.md.

## Delivery preparation

Candidate404 integrates399instrumentation/testedbinary and401trueVBoxsoftware
boot/input evidence. Checked-in executable is exacttested399 build
f868a8dae9664e469b2011390547c5ca, sourceb7e17c09679eb3e78e1be9895d2d5be550a06391,
SHAd8257d14791c7f1cee6050c250a4327cb35bde75e0bf0036c1bbc470b939ceaa.
Integratedhostsuite pending. Rootreview/devpush/hostedCI pending; lastcompleted
delivery remains c1f64d0/tested395 hostedCIgreen. Main unchanged.
TrueVBoxMetal/GPUtransport,SMPtimekeeping,gracefulGUIshutdown,4K60 andfresh-user
console-only installation remain open. Softwaredesktop is not acceleration.
