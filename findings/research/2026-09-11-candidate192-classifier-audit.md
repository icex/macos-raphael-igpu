# Candidate 192 generic-fault classifier audit

The VMID11 worker diagnostic can distinguish only the page-table state observed
after the fault latch was copied and cleared. A stable context snapshot says the
seven context registers did not change during the worker's two reads; it does
not establish their values at fault time, and page-table reads remain non-atomic.
Without per-client prepared-request correlation, the result cannot attribute a
bad root or child entry to a particular preparation, conversion, or invalidate.

The classifier now accepts a generic client fault group only when one parent
record has exactly one relative and one absolute view and each view has entries
numbered consecutively from zero through its declared count minus one. Orphan,
cross-status/address, missing-view, duplicate, and count-inconsistent generic
records become capture loss. A structurally impossible sequence is definitive;
a proper prefix is non-definitive because the independent COM2 snapshot worker
can freeze its record count between the observation worker's `CRLOG` calls. The
live coordinator therefore waits for a later cumulative snapshot and rejects an
unfinished prefix if it remains at the exposure deadline. Historical VMID1
parsing and verdict behavior remain unchanged. The shared two-slot driver store can still be filled
by earlier client faults, so a future candidate 192 run is not guaranteed to
capture VMID11; aggregate capacity rejection is evidence of that limitation.

The precise test question is: at the later worker observation, is the VMID11
root inside the framebuffer aperture, and at which level does each current
relative/absolute walk stop? That partitions the observed current root versus
child state, but does not prove the fault-time root cause.
