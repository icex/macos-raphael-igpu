Experimental RaphaelGPU 1.0.162 diagnostic snapshot for Sequoia 15.7.9 (24G830).

- Adds opt-in `rgpuhybrid=1` observations around hybrid-engine creation, with exact
  HWLibs entry checks and unchanged native return values. This diagnostic has passed
  compilation/static checks but has not been tested on the physical GPU.
- Clean-run evidence now proves three native KIQ setup stamps execute. PSP firmware
  destinations match the active instruction-cache mapping.
- Full Metal acceleration remains unavailable: hybrid-engine creation returns status 4
  and the native probe fails before completing any command buffer. No games are verified.
- Adds bounded ACPI shutdown attempts while preserving the original hard stop deadline.
  Guest/container exit does not prove that the GPU has quiesced.
- Adds a route-table binary ownership check that rejects the earlier wrong-base hooks.
- Corrects the diagnostic record and adds source-built release archives, checksums and
  a build manifest. Experimental 1.0.160/161 hooks are excluded.

The host has hard-hung during earlier passthrough experiments; the cause is unresolved.
This prerelease is for research and is not a stable or game-ready driver.
