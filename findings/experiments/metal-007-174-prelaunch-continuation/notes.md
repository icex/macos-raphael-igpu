# metal-007 / candidate 1.0.174

This was the single approved continuation of run
`e583a1b2d97a4ad3b607c1d20a29a812` on host boot
`5d6f45d0-4384-4340-b819-7751bc26ebb3`. It loaded candidate 1.0.174 build
`b60df7448ea24106ae4300f6760cb171` under CID
`68919eed2dce887271e257ef6dca7f1849d4917bcfbb0b31496fdb82f7654614`.
The replacement manifest SHA-256 is
`535ab074affacd019ce9fb389cb9657f610d6cbf7dcca7738de5cc7d298f0ddc`.

The earliest concrete failure was PM4/KIQ startup preflight. Serial multiplexing split the
diagnostic across lines 2918 and 2920; together it reads:

```text
XQ2: preflight failed: BAR0 mapping unavailable
XQ2: startKIQ refused: preflight or genuine dequeue failed
```

The PM4 MQD initialization immediately before this returned one, but the PM4 engine `powerUp`
returned zero. Native partial cleanup while the guest mappings remained live returned one;
`AMDHardware::powerUpHWEngines` and `AMDGraphicsAccelerator::powerUpHW` then returned zero.
There was no KIQ submission, SDMA VM program, VMID-2 callback or page-table walk. The
candidate-173 VMID-2 root repair and corrected walker therefore remain untested on hardware.
The classifier returned `INCONCLUSIVE / sdma_vm_program_missing`; that label captures a missing
later observation and must not be interpreted as an SDMA execution fault because no queue started.

The guest honored the bounded shutdown request and reached CPU halt. `shutdown.json` records
`exited-after-guest-request`, boot UUID `4E5C12A8-F7E3-41A4-96A3-53FDF0232E90`, and request
`db3f5472fbf74e5a93e996116526407c`. Host state before and after is identical, and the captured
kernel interval contains no GPU, IOMMU, reset or fault report.

Recovery failed closed with `guest host-KIQ lifetime reservation is absent or invalid`: startup
never activated the exact host-KIQ reservation. This recovery result does not authorize warm
reuse or another launch. The continuation's durable one-shot marker has been consumed and the
boot ledger remains unchanged.

The JSON, JSONL and serial files in this directory are byte-for-byte copies of the immutable
coordinator output. `prelaunch-einval-probe.json` and `prelaunch-readiness.json` preserve the two
pinned continuation inputs. [SHA256SUMS](SHA256SUMS) records every copied artifact; in particular,
`serial.txt` hashes to `0ba1b171ed24a2da8b8bd449ac5fb897abdfe33f788192f3c08cc42f294ba2bc`
and `verdict.json` hashes to
`b11468673394fc77413d2b76ca27ea45a48a2122a0742d56e6549a3e4556f652`.
