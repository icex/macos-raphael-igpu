# Candidate 187 frozen run

The PCI slot correction worked through admission and guest identity: the VFIO
endpoint was observed at `pcie.0` slot 6 function 0, matching the OpenCore
`PciRoot(0x0)/Pci(0x6,0x0)` path, and `marked=1` was observed. Native readiness
also progressed: SDMA topology was applied, the XH2 lease was OWNED, the pool
became ACTIVE, KIQ succeeded, and PM4/SDMA0/VCN0 engine power-up completed.

The run then produced a VMID1 fault (`0x101b3a`) at VA `0x400580000`; the
captured walk identified root `0xf40b6ff000`, relative PDE physical
`0x84b700000`, and a missing leaf at index 1408. No Metal probe result was
obtained. Critical capture remained incomplete at the 180-second deadline,
so the classifier returned `INVALID` with `capture_loss`; recovery was refused
because the CR2 attempt exceeded the terminal prefix and no receipt exists.

This is GPU cycle 9 overall, cycle 5 since the post-182 Astra review, and cycle
1 since the post-186 Astra review. Route installation and engine startup are distinct and both passed;
the later VMID1 fault and capture loss prevent a functional acceleration claim.
No retry, reset, rebind, manual cleanup, or additional launch is authorized.
