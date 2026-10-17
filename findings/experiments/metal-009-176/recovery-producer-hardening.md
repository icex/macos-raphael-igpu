# Post-run recovery producer hardening

This note records an offline correction made after candidate 176. It does not describe the producer
that generated candidate 176's immutable schema-6 receipt; that historical producer remains SHA-256
`8ff51636013da702fed170933ef69f62ae15bbf91d1e59011dc140b9782ee39d`.

The reviewed candidate-177 producer moves the live-GART preflight into
`consume_host_kiq_reservation`. After authenticating the active 72-byte descriptor and before its
first zeroing write, every caller now derives the framebuffer aperture and complete live GART range,
then rejects overlap with the descriptor or any temporary host-KIQ write span. The standalone
retirement path consumes through this guard. Normal recovery reaches it after the read-only graphics
pipe guard and before quiesce. The existing independent GART derivation and scratch-overlap check
still runs immediately before the temporary KIQ writes, so the earlier preflight is not reused as
stale metadata.

Independent review approved this ordering. Six focused descriptor/scratch-overlap and malformed-root
cases reject before any VRAM write, and the complete recovery module passes 69 tests. Final reviewed
SHA-256 values are:

- `tools/vfio-recover.py`: `1212c60b706f1c55b688bd45ba97fc28f28b75c08c996275041c1a7b71983453`
- `tests/test_vfio_recover.py`: `2918a4f017f604f39722ddcc4dbeee6ab15b9800073a979fd02f456fbde9fd47`

No hardware access, receipt rewrite, ledger change, launch, or reset occurred during this hardening.
The historical range audit remains unchanged at SHA-256
`a6ad51f95e3608f47afd951f970c3f4ed849db8ad0e0aee225790c1d26875ae2`.
