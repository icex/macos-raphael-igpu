Experimental RaphaelGPU 1.0.181 candidate for macOS Sequoia 15.7.9 (24G830).

Candidate 1.0.181 extends `rgpuvmroot` to mode 3: after the proven VMID2 root repair, child page-directory entries (`AMDGFX10VMM::getPDEValue`) and video-memory page-table entries (`getPTEValue`) are converted from the framebuffer MC aperture to the physical carve-out form through the same guarded aperture arithmetic. Critical replay schema 2 gains the reviewed terminal-prefix corruption tolerance. Metal execution remains unverified until measured.

- Accepts the zero low-attribute VMID2 root observed in candidate 1.0.179 only
  within the existing Raphael, hub-0, VMID2, reprogram, aperture, and exact
  prepared/live-root guards, allowing the guarded BAR-to-MC translation to run.
- Adds bounded, checksummed CR2 critical-record replay. Complete build-pinned
  snapshots reconstruct records up to 511 bytes without relying on the host's
  observed 255-character log-line limit.
- Adds a persistent monotonic schema-3 recovery lifetime marker bound to the
  launch nonce, native OWNED descriptor, and ACTIVE software-pool record. Host
  recovery requires exact VALID readbacks before recovery and directly before
  any dynamic scratch write; a published abort fails closed.
- Retains candidate 1.0.179's native 68 MiB VMM arena, recovery-lease exclusion,
  submission/backing observers, and the unchanged bounded Metal probe.
- Offline sanitizer, source-contract, whole-driver syntax, route ownership, and
  exact 24G830 KDK preflight checks cover this candidate. Hardware execution has
  not yet validated the root-translation hypothesis or schema-3 cleanup path.

The last hardware candidate enumerated Metal 3. No compute or render command buffer has completed,
accelerated desktop composition is not verified, and zero games are supported. This
remains a research prerelease with three historical host hangs; all bounded launch,
watchdog, recovery, and no-reset rules remain in force.
