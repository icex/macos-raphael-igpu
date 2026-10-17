# Candidate 426: preserve stock virt-manager import order

Native 421's first guarded manager failed before connection with a circular `virtManager.baseclass` import. The early `details.viewers` import entered config → inspection → baseclass while baseclass was incomplete. An offline subprocess using the original launcher sequence reproduces that exact ImportError against installed virt-manager 5.1.0. An earlier oversimplified control also failed on Gdk version selection; it is preserved separately and is not the circular-import proof.

The corrected launcher imports stock `virtmanager` first and wraps `_import_gtk`. The original hook finishes GTK/config initialization before the guard imports viewers or changes its session constructor; the original return value is preserved. Session policy and `run_manager(on_session=...)` callback semantics are unchanged. Connection remains later in stock `runcli`.

Nine focused tests pass, including successful hook ordering and refusal propagation when stock initialization fails. An additional subprocess imports the actual installed manager and new 424 client libraries, suppressing **only `Gtk.init`** to avoid a graphical session. It completes stock config imports, installs the constructor guard, and confirms process-local auto-redirection is false. No SpiceViewer, Spice session, USB device manager, VM or GUI is instantiated. This is import-order proof, not native startup or USB qualification; root owns live validation.

[Evidence hashes](console-manager-import-order-evidence-20261010.json) preserve both controls, actual import smoke, and tests. Candidate 421 and installed source were not edited.
