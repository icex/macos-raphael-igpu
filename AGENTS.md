# Standing project instructions

## Objective and execution

- Deliver functional macOS desktop Metal acceleration on the Raphael iGPU, with
  repeatable cleanup after guest crashes or QEMU closure and without host crashes.
  Metal enumeration alone is not success.
- Read `status.md` before continuing; verify live host and repository state before
  hardware work. Older reports may contain superseded conclusions.
- Use agents to write and test code; the primary agent coordinates and audits.
- Select lower-cost agents by task: prefer `gpt-5.6-luna` for routine edits,
  packaging, and execution of reviewed test/staging procedures; use
  `gpt-5.6-sol` for driver/recovery implementation and difficult debugging.
  The coordinator audits results. Do not interrupt an active hardware operation
  or build merely to switch models. Preserve the mandatory Astra review below.
- Check for regressions on every change and hardware cycle. Keep frozen evidence
  intact and distinguish unobserved behavior from a demonstrated regression.
- Update `status.md` with technical evidence and show a brief progress table and
  blocking issue after each hardware run.
- Do not merge or push to main until full acceleration works. Prefer meaningful
  milestones over frequent development commits and release builds.
- Preserve existing host safety and experiment gates. Never bypass exhausted run
  budgets, cycle vfio-pci through amdgpu and back, or use `sudo -n` probes.

## Mandatory adversarial review after stalled testing

User instruction recorded 2026-09-10:

After **more than three consecutive GPU test cycles with the same unresolved
issue** (the fourth cycle), pause routine hardware retries and dispatch a
**gpt-6-astra agent with reasoning effort xhigh** using this exact prompt:

> review whatever the current status.md of this project is, check its documentation, methodology, tests, experiments. figure out why this fails and report back in a report-astra.md file for other agents to review

- Refresh `status.md` before dispatch. Include the failing boundary, consecutive
  cycle count, run identifiers, hypotheses, regression comparisons, and evidence.
- Count actual GPU experiment cycles, not builds, unit-test invocations, or repeated
  parsing of the same capture. Renaming a candidate or changing an unproductive
  hypothesis does not reset the count. Reset only on demonstrated meaningful
  progress past the issue; document the evidence.
- Track the issue and count in `status.md`. If inherited history is uncertain,
  reconstruct it from run evidence rather than claiming a zero count.
- Archive any existing `report-astra.md` under a unique dated research path before
  the reviewer writes the new report; preserve original report contents.
- The review is offline/read-only except for its report: no VM launch, device
  access, sudo, resets, or implementation edits. Provide these boundaries alongside
  the exact prompt.
- Have the coordinator and implementation agents assess the report, verify its
  claims against evidence, and record a revised hypothesis and discriminating test
  before resuming hardware cycles. A report is not permission to bypass safety gates.
- The user also authorizes an optional Claude Code review using the same prompt.
  If available, adapt only the output filename to `status-claude.md`, preserving
  the coordinator's authoritative `status.md`. Do not claim a Claude review ran
  unless it actually did. The mandatory trigger remains the Astra review.
