# Scanout self-refresh experiment317

Candidate315 enabled HDMI firmware commands, but physical output remains black.
316 actually selected native1080p120, confirmed CG mode and OTG2199/1124, without
physical confirmation. Active DPG_CONTROL0 shows the blank color generator is no
longer covering scanout. HUBP reports timeouts/underflows; SURFACE_INUSE is0.

Existing forceDramAllow ORs33 into DRAM_STATE_CNTL. Its comment explicitly accepts
underflow to keep SMU responsive when display clocks are not running. Linux
`dc/hubbub/dcn10/dcn10_hubbub.c:hubbub1_allow_self_refresh_control(false)` instead
uses SR force-enable1, force-value0 to prevent self-refresh while scanning.

317 opt-in rgpudcnnostutter=1 retains33 until firmware is responsive. While any of
four OTGs has MASTER_EN requested, clears only bit0: SR value0/enable1, P-state
force bits unchanged. Applies after successful firmware reload, DRAM writes and
OTG control writes. When all OTGs are off it restores the previous safeguard.
No clock frequency changes, DMCUB changes, VRAM writes or rebinds introduced.
Falsifier: readback1032 with active scanout still black and no surface fetch would
reject forced self-refresh as a sufficient explanation. Sticky underflow flags
alone cannot establish that a new underflow happened; physical observation and
surface-in-use progression are the primary observations.

316 critical snapshot5 was valid with501records, final snapshot8 reported512 plus
147 dropped. Earlier valid snapshot is retained as c316-prior-valid-critical-records.txt,
not substituted for the failed final receipt. Removing316's repeated color logs
and sampling successful SUB summary/backing and DMUB delivery records (existing
SuccessRecordBudget, first4) leaves failures critical and every sample on serial.
No parser tolerance, capacity, recovery or capture-fatal rule is weakened.
