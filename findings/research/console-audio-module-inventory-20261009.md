# Pulse module inventory compatibility

Candidate358's first audio controller attempt failed before any route/module
mutation: the installed `pactl -f json list modules` entries omit `index`.
Treating a list position or PipeWire `object.id` as the Pulse module ID would
not establish ownership for unload/restore.

Candidate360 reads authoritative IDs from `pactl list short modules`. Arguments
can span lines and contain tabs, so records are separated by numeric ID/name
headers, with the final tab delimiting usage. Names, IDs, usage and record shape
are validated; duplicate IDs and ambiguous/malformed records refuse. Identical
module names retain their distinct IDs and existing unique-ownership checks.
The command wrapper preserves trailing tabs by removing only final newlines.
No route/default/volume or lifetime gates change.

Read-only verification on the actual host parsed17 modules and matched every
(name, argument) pair against the JSON inventory; the full backend snapshot
succeeded. Receipt: `/home/bogdan/macos-vm/run/c360-module-inventory-check.json`.
17 focused tests pass, including realistic multiline/empty fields, large Pulse
IDs, duplicate/ambiguous records and existing replacement/restoration failures.
No audio mutation, guest operation or native VM control occurred. Live route,
recording and restoration remain for the hardware owner to qualify.
