# Candidate 174 startup no-queue cleanup

This directory preserves the exact immutable artifacts from the one root-cleared
startup-only cleanup on host boot
`5d6f45d0-4384-4340-b819-7751bc26ebb3` for prior run
`e583a1b2d97a4ad3b607c1d20a29a812`.

- Build ID: `b60df7448ea24106ae4300f6760cb171`
- Attempt ID: `f11105d537dd4ff097476de97a7620a4`
- Recovery ID: `70463a1f1b3e4dc4899a175e64103df8`
- Startup cleanup source SHA-256: `bed28d30c1c707156f78c29aa846698b292d007e6500f8ef528b77292e6959fc`
- Pinned failed inspection SHA-256: `42b7549d1964a5c4f7117c08afb246a3c406f0817e4374c8df2b51280d823d9c`
- Ledger preimage SHA-256: `2d15f0cbb73d71e8efaf2a951f13c707726e9b98279a0e85208253f1941410d3`

The command returned exit code 0 and was not retried. The exact schema-4
receipt validates successfully. Fresh admission found all 64 HQDs and both
graphics pipes inactive, every observed HQD doorbell zero, SDMA PAGE/RLC/GFX
inputs disabled, AUTO_CTXSW disabled, and STATUS.IDLE set. The bounded
transaction halted CP, changed exact SDMA F32 from 0 to 1, received exact PSP
`DESTROY_RINGS` and `DESTROY_GPCOM_RING` acknowledgements, repeated the full
idle scan, then consumed the exact 72-byte PENDING descriptor last. Host and
journal gates remained stable, and the launch ledger was not changed.

This proves only that the pinned startup-noqueue cleanup transaction succeeded.
It does not prove recovery after a full initialized guest, repeated full-guest
recovery, a subsequent launch, or Metal functionality. The one-shot attempt is
permanently spent and must not be rerun.
