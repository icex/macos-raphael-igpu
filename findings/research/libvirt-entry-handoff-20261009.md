# Candidate341: host permit and real container controller

The native libvirt profile is wired into the existing manifest, launcher and
supervisor. QEMU is created paused; the host verifies its exact container,
process, configuration, network provenance, capture drains and original deadline
before publishing one exclusive resume permit. Module hashes bind the deployed
controller. The original container deadline remains unchanged. Docker init reaps
the private libvirt session's child processes.

## Observed software results

The actual `libvirt-console-entry.py` launch, permit validation, runtime monitor
and cleanup ran against a real libvirt11.9/QEMU10.1.2 TCG guest. A research adapter
substitutes the previously tested software boot disk and isolated TAP for the
native macOS/VFIO configuration and network verifier. No KVM, VFIO, host NIC or
macOS disks are accessible to these containers.

- `run/c341-entry-valid-2ac1ff25/result.json`: independently inspected paused
  identity agrees; no guest UART byte arrives during the pre-permit interval.
  The valid permit produces the matching running receipt, the guest sends its
  readiness byte, accepts a shutdown byte, and powers off. Terminal reason is
  `guest-shutdown`, exact QEMU process exit is checked, container exits0.
- `run/c341-entry-wrong-permit-1e73a9cf/result.json`: changing the PID start time
  in the permit produces an identity refusal. No running receipt or runtime
  running event appears; owned cleanup records stopped and container exits1.

Both containers are stopped. Ten host integration tests exercise the real
`release_libvirt` and handoff files with mocked Docker, topology and drain probes:
capture failure/loss, replaced process, changed image/network, admission and
shorter handoff deadline expiry, successful binding, and replaced running receipt.
Review found a missing final check of the shorter30-second handoff budget; it now
refuses before permit publication, while preserving the independent exposure cap.

## Scope and next observation

This proves the real container controller boundary with a software configuration
adapter, plus host release ordering under injected external observations. It
does **not** prove production serial drains with a libvirt-managed macOS guest,
native inherited macvtap transfer, GPU execution, or GPU recovery. The next
admitted cycle must demonstrate those together. The existing direct profile is
still available and the tested340 driver behavior is unchanged apart from the
new candidate version/build identity.

Reproduction: run [host driver](libvirt-entry-handoff-host-20261009.py), using the
retained16MiB software boot image from the earlier lifecycle fixture. The
[container adapter](libvirt-entry-handoff-smoke-20261009.py) documents every
substitution. Raw result, controller events and container logs remain in each
run directory. These tests deliberately do not use or consume GPU ledger entries.

## First native launch refusal

Run38ca74a82e750f36f3f70fc6859951d3 reached the container entry but its pure
planner rejected an uppercase NAT MAC. The traceback precedes libvirtd and
QEMU creation; no guest UART captures exist. The launcher stopped and produced
INVALID; its reservation remains in the ledger. The corrected parser preserves
MAC spelling and accepts the complete actual expanded launch command offline.
No driver regression can be inferred from this pre-QEMU failure.

The ordinary recovery tool cannot operate on a missing guest lease. The existing
schema8 empty-capture stopped-queue qualification had an obsolete three-launch
limit; it now follows the current audit-only count policy, preserving latest-run,
unique identity, exact manifest/ledger/helper hashes and the full hardware scan.
The cycle wrapper forwards the explicit prior evidence so this path remains under
the normal experiment locks and supervised lifecycle. No manual ledger deletion,
synthetic recovery receipt, reboot or rebind is used. Live qualification of this
retry still remains required.

Attempt341b (47b605e5a87721e18092c98e48376ea8) performed the full stopped
scan but refused before new reservation or guest launch: the schema8 validator
expected only0x80030000. The observed0x800c0000 is the exact final successful
DESTROY_GPCOM_RING reply, confirmed in340c's recovery commands and in the current
`vfio-recover.py` two-command teardown. The corrected default allows exactly
READY_FLAG|DESTROY_RINGS or READY_FLAG|DESTROY_GPCOM_RING; generic ready, busy,
error-bit and other-command replies still refuse. Explicit mailbox expectations
used by the separate MODE2 recovery validator remain exact. Both retained scan
passes are complete, inactive and identical; journal cursor and host gates pass.
Offline replay now validates, but no stale proof is reused for a new launch.
