# Candidate 175 retained host-KIQ MQD diff

This is an offline comparison of the create-once retained-scratch observation against the
exact `_host_kiq_image()` produced by `tools/vfio-recover.py` at Git commit
`7db5a73d0ec830f31d80c4975e7a36c2f017326a`. No device was opened for this comparison.
The observation remains nonauthorizing and does not amend the incomplete schema-5 receipt.

## Immutable inputs

- Observation/result SHA-256: `f0282d7b51ad2a6f962c03c0bb467c9e5058784a0055a427697bbb4e31eee4f8`
- Device-attempt marker SHA-256: `575a8483caeb1eb190edefbca3d728a9fe07a2c3f23a2d5216e6cb6b3ef3d49d`
- Historical recovery source SHA-256: `b0ca780828e615d6ad5d17b360d739c1619e279e4f0e37077eb0c79ecb697298`
- Observed MQD SHA-256: `3329c7874b030528c47fb6946858820a5b8847537e065ef17dc40d867460b3c7`
- Reconstructed initial MQD SHA-256: `16a5ac13ab60793ab8e7f2d8975c61805e2f864ddf93d35a655111a6f123ab89`
- Stable aggregate scratch SHA-256: `d5e284bcca69d81bbc6bf1a437a2f50ed5c55025778783de5cc2a5468511eafd`

Both capture passes were byte-identical for every range. The MQD differs in 14 bytes across
exactly six of its 512 dwords; the other 506 dwords match the initial image.

## Raw dword diff

The field names and dword indices are from Linux v6.12
[`struct v10_compute_mqd`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/include/v10_structs.h#L757-L765).

| Byte offset | Dword | Field | Initial | Retained | XOR |
|---:|---:|---|---:|---:|---:|
| `0x158` | `0x56` | `cp_mqd_query_time_lo` | `0x00000000` | `0x12fbe02c` | `0x12fbe02c` |
| `0x15c` | `0x57` | `cp_mqd_query_time_hi` | `0x00000000` | `0x00000106` | `0x00000106` |
| `0x168` | `0x5a` | `cp_mqd_connect_end_time_lo` | `0x00000000` | `0x12fbe020` | `0x12fbe020` |
| `0x16c` | `0x5b` | `cp_mqd_connect_end_time_hi` | `0x00000000` | `0x00000106` | `0x00000106` |
| `0x174` | `0x5d` | `cp_mqd_connect_end_pq_rptr` | `0x00000000` | `0x00000100` | `0x00000100` |
| `0x178` | `0x5e` | `cp_mqd_connect_end_pq_wptr` | `0x00000000` | `0x00000100` | `0x00000100` |

The two reconstructed 64-bit time values are:

- `cp_mqd_query_time = 0x0000010612fbe02c`
- `cp_mqd_connect_end_time = 0x0000010612fbe020`
- query minus connect-end: `0x0c`

The retained external pointer bytes are exactly
`00010000000000000001000000000000`: current report `0x100`, zero gap, and stored WPTR
`0x100`. The retained fence is the ring's unique nonzero sequence `0x667b2f65`. The EOP
allocation remains all zero.

## Interpretation

The historical builder zero-initialized all six changed fields. After publishing the MQD,
the host recovery never issued another CPU BAR0 write to the MQD. The changed fields form a
coherent queue-lifecycle record: two adjacent 64-bit timestamps, followed by matching
connect-end RPTR and WPTR values at the submitted end position `0x100`. No programmed base,
control, doorbell, VMID, EOP, or other MQD field changed.

This pattern is strong evidence of hardware/CP MQD writeback rather than arbitrary scratch
corruption. In particular, `cp_mqd_connect_end_pq_rptr=0x100` was not present in the CPU-built
image, so it independently records that the queue reached the submitted end pointer. The
exact retained `WRITE_DATA` fence value shows that the final packet eventually executed.
Together they resolve the old missing-fence result as a polling-time or visibility ambiguity,
not packet nonexecution.

The exact lifecycle event which caused the MQD writeback remains unresolved. The original
failure path subsequently halted MECs and forced the temporary HQD inactive during cleanup;
the connect-end fields could have been committed at that boundary. The retained observation
cannot establish when the fence became visible during the original poll and cannot prove that
the graphics UNMAP completed before forced host cleanup. It therefore cannot complete the old
receipt or authorize another launch or recovery.
