# Live amdgpu reference before VFIO handoff

Captured 2026-09-11 after boot `1c707768-e0e1-4d85-8640-50706e724c08`, while
`0000:7b:00.0` was still owned by Linux `amdgpu`. The raw connector and IP
discovery captures are in `findings/hw/`.

## Confirmed host facts

The host driver reports the same core topology assumed by the macOS plugin:

```text
IP DISCOVERY 0x1002:0x13C0
VRAM: 512M 0x000000F400000000 - 0x000000F41FFFFFFF
BAR=512M
GART: 1024M 0x0000000000000000 - 0x000000003FFFFFFF
PCIE GART ... table at 0x000000F41FC00000
reserve 0xa00000 from 0xf41e000000 for PSP TMR
kiq ring mec 2 pipe 1 q 0
SE 1, SH per SE 1, CU per SH 2, active_cu_number 2
```

Live IP discovery reads are GC `10.3.6`, SDMA0 `5.2.6`, MMHUB `2.4.1`,
ATHUB `2.4.1`, NBIF `7.3.0`, UMC `9.5.0`, SMUIO `13.0.10`, MP0/MP1/MP2
`13.0.5`, and DM `3.1.5`. This validates the silicon versions used by the
plugin's remap table; it does not prove that every Apple register path is
correct.

## Display topology

Linux sees five DRM objects on `card0`: HDMI-A-3, DP-3, DP-4, DP-5, and a
writeback connector. HDMI-A-3 is `connected`, `enabled`, and `dpms=On`; the
three DP connectors are disconnected. The kernel initializes **DCN 3.1.5**,
reports `DP-HDMI FRL PCON supported`, and registers the iGPU framebuffer.
The connector sysfs EDID file is empty even though HDMI-A-3 is connected, so
an empty EDID here must not be interpreted as proof that no sink exists.

This is new evidence that the physical HDMI path exists and is active under
Linux. It does not justify forcing HPD or injecting a generic EDID into the
macOS kext yet: the missing piece is the APU's ATOM display-object table and
its connector mapping. The Linux connector names and the VBIOS identity are
the reference data for reconstructing that table.

## Consequences for the macOS implementation

1. The guest's `512 MiB` framebuffer aperture and `10 MiB` PSP TMR reservation
   match the host's native values. The previous allocator failures therefore
   are not caused by a 7 MiB QEMU display adapter.
2. The host GART is a **1 GiB** aperture with the page table at MC
   `0xf41fc00000`. Any guest diagnostic that assumes a 256 MiB GART or places
   scratch pages in the final 4 MiB must be rechecked against this layout.
3. Linux creates KIQ on MEC2 pipe 1 queue 0 and programs one active compute
   engine configuration. The guest's `MEC2`/pipe-1 observation is therefore
   topologically correct; the remaining failure is queue state, memory
   allocation, or packet fetch, not an incorrect engine selection.
4. Host firmware loads DMUB `0x05003300` and initializes DCN 3.1.5. The macOS
   path has not demonstrated equivalent DMUB/DCN initialization. Desktop
   acceleration and physical HDMI output must remain separate acceptance
   criteria.

The register BAR was not read in this capture because debugfs is not exposing
`amdgpu_regs` and raw BAR reads are nonresponsive while `amdgpu` owns the
device. A privileged read through the driver's debugfs interface is the only
remaining read-only host comparison; it must happen before VFIO handoff if we
want CP/RLC register values from the working Linux state.
