# Candidate 417: identify the hardened VBox process without ptrace access

Candidate 415 refused its fixed root probe because /proc/PID/exe was inaccessible.
This change preserves the exact owned UUID/config/running check and pins PID plus
start time, but obtains the PID from the private owned VM's VBox.log header. The opened log must match its recorded
inode/device/owner, and symlinks are refused.
The process must have the current user's real/effective/saved/filesystem UIDs,
the exact --startvm UUID, and an expected installed executable command path.
That installed file must be a regular root-owned file without group/world writes.

A readable kernel executable link must match. Only EACCES uses the
explicitly labelled owned-session/log/process evidence instead; missing or
mismatched links refuse. This alternative does not prove the executable through
the kernel and is not authentication against a malicious process of the same UID.
The existing exact session and fresh private log provide the association for this
controlled single-owner test. PID start time, argv and liveness are checked twice;
changes to the pinned process/log/binary identity refuse subsequent requests.

Focused tests cover hardened EACCES, missing/mismatched executable links,
foreign/duplicate UUID arguments, ambiguous/missing log PIDs, mismatched credentials,
writable executable paths, dead processes, PID reuse and log symlinks. The fixed
read-only payload, one-shot command, private listener, response limits and 300 s
watchdog are unchanged. No GPU, firmware, framebuffer or Apple binary modification.

Root prepared independent bootI reflinks from naturally stopped bootH, with receipt
run/c398-vbox-clones/boot-i-preparation.json. The next native run uses the same
virtio NAT/VMSVGA profile. Success requires an actual framed UID0 response and
inspection of build, network and framebuffer contents. A passing process check
alone does not prove the guest command ran. The same GUI remains available for
awake checks and normal guest shutdown; no remote shutdown command was added.

Final integrated host validation: 1496 tests ran, eight skipped, in 56.577 seconds;
all remaining tests passed. Log run/c417-final-full-suite.log. Native result remains pending.
