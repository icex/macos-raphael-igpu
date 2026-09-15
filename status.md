# Live status — 2026-09-15

260 readback returnedffffffff for all selections; encoder stalled, desktop passed,
forced shutdown, recovery recovered. Artifact candidate-260-attempt-readback-results.
261 tests inherited DPG_MODE remaining set during earlier native static runs.
Native static clears0x103 but preservesbit2; Linux stop_dpg explicitly clearsbit2.
Guarded clear before static initialize, PSP firmware placement, native reset hold.
Hardware result pending. No encoder solution claimed.

## Completed261
Run dff020605f965e42a43c9f4eba6fef0e, build7bd20b251b6a44d5b76b15a0f52fcbcc,
MODE2 #117, full suite935tests (three skipped), desktop CORE_PROBE_PASS.
VCNMODE905->901; native static finished with POWER_STATUS800. PGFSM wait
caller935f1 expected0/mask3f3fffff returned0, observed00800000 maskedto0.
CacheBAR and SOFT_RESET remainedffffffff; other VCN registers accessible.
HardwareH264 selected accelerator4294968053; frames0/1accepted, frame2stalled.
Shutdown forced; recovery recovered; host-after VM=false/vfio-pci/pinned.
Results candidate-261-results. Mode correction is insufficient; power-on wait
failure is not the demonstrated blocker. Allowance consumed.

Next investigate retained VCN state: native platform helper only sendsPowerUp6,
whereas Linux Raphael supportsPowerDown5 thenPowerUp6. MODE2 gfx register
receipts do not independently establish a VCN domain cycle.
