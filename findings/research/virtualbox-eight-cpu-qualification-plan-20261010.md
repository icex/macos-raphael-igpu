# Candidate406: qualify eight-vCPU input, awake state and shutdown

Fresh branch from fetched dev84159a9, merged403's observed desktop result and narrowly bounded cleanup-query retry. No VM has been registered or started. BootE loader/system VDIs are independent descendants of the preserved398 baseline VDIs; the main images and prior attempt disks were not accessed or written. Loader content compares to the unbooted retained bootB raw loader and has the same SHA2569c637e66242be0a513687ac9a015f892968d6d204972b5d409a05a736c855b06. System preparation uses a reflink without a large disk reread. No new EFI change is introduced.

Root executes only after402 is completely stopped:

```sh
python3 -B tools/vbox-clone-boot.py --execute \
  --loader /home/bogdan/macos-vm/run/c398-vbox-clones/OpenCore-e-boot.vdi \
  --disk /home/bogdan/macos-vm/run/c398-vbox-clones/mac_hdd_ng-e-boot.vdi \
  --smc-key-file /home/bogdan/macos-vm/run/c398-vbox-clones/smc-key.private \
  --output /home/bogdan/macos-vm/run/c406-vbox-boot-e \
  --seconds 300 --cpus 8 --tsc-mode RealTSCOffset
```

The key remains file-only/private. Confirm actual logs report eight CPUs and RealTSCOffset at the calibrated host frequency (prior403:4699997773Hz); retain raw private logs and sanitized clock observations separately. This is the same coupled clock regime as403, not a new TSC intervention.

## Root's bounded guest checklist

1. Observe the actual VBox desktop and any Keyboard Setup Assistant. Dismiss/complete the visible dialog normally before testing Terminal; do not infer input from a screenshot alone.
2. Through the owned window, type `printf 'VBOX406_INPUT_OK\n'; /usr/sbin/sysctl -n hw.ncpu; /usr/bin/sw_vers -buildVersion`. Capture the visible marker, CPU count and build. Guest command execution is not authorized to this planning agent.
3. Create only the test's user LaunchAgent job, without shell backgrounding:
   `launchctl submit -l org.raphaelgpu.c406.awake -- /usr/bin/caffeinate -di -t 240`.
   Verify its PID via `launchctl list org.raphaelgpu.c406.awake` and corresponding display/user-idle assertions via `pmset -g assertions`. This avoids Terminal owning a background caffeinate child. No sudo or persistent preference change is required.
4. At approximately180 seconds from controller start, remove only that label with `launchctl remove org.raphaelgpu.c406.awake`. Verify the job and its PID's assertions disappeared before shutdown. Do not stop other awake jobs. Its240-second timeout is a fallback, not evidence of orderly removal.
5. Request ACPI shutdown through the exact owned VM. Inspect the actual dialog before confirming Return. Record that no Terminal job confirmation blocks shutdown. Observe VBox's powered-off state and bounded unregister completion before the300-second controller deadline. Do not label deadline poweroff natural shutdown.
6. Retain UART, screenshots, clock observation, user input/awake evidence, shutdown request time, controller result and any retry errors. Confirm exact UUID/configuration absent from the private registered list. Never rewrite an original error receipt; reconcile separately if needed.

Acceptance: observed keyboard marker, hw.ncpu8/build24G830, explicit awake assertions and their removal, no recurring clock panic during this bounded test, and poweroff before deadline plus successful ownership-checked unregister. The software desktop still does not establish Metal, Raphael passthrough, a VBox presentation driver or sustained performance. If input/boot consumes the shutdown margin, request shutdown earlier rather than extending the deadline or assuming success.
