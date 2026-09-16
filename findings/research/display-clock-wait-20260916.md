# Display clock warnings and hidden wait diagnostics — 2026-09-16

Offline analysis of supplied 24G830 Framebuffer decompilation and native assembly,
correlated with run2afa3401a71e99091aa8bdbd14c50fa7 serial lines1894 onward.
No driver patch, register write or extra hardware exposure.
[Binary comparison and serial hash](display-clock-wait-evidence-20260916.json).

The dccg2_get_dccg_ref_freq:89 print comes from0xd8412. It reads two fields from
one register through0x110841; when the first field is nonzero it prints, then
unconditionally writes its input frequency to the output and returns. The second
field does not affect this function's return path. This warning is not a trap or
an error return. The underlying register expectation can still be wrong.

hubbub2_get_dchub_ref_freq:565 comes from0x13bf39's second extracted field being
zero: the native branch writes the input frequency to output and prints line565.
The alternate branch can halve the input based on the first field and has a
separate range warning at line558. The observed565 therefore identifies the
fallback branch, not the range-warning branch. Actual input frequency, register
address and raw read value remain unobserved.

Later generic_reg_wait:513 is a real exhausted polling condition in0x110bd7,
followed by logging and return; it is not an exception or GPU recovery operation.
The function already passes the originating function name and source line to its
internal logger0x169b83, but that detailed timeout text is absent from this serial.
The logger tests a category mask at logger+0x20. More decisively, its console sink
0x169cf6 requires entry category0 in addition to console-enable and nonempty text;
the wait timeout uses category1 (the slow-success message uses3). Merely enabling
the category mask would not make this sink print category1. Ring-buffer retention
has a separate flag and was not observed live.

All internal instruction bytes in these six functions match the exact KDK file.
The recorded differences are external CALL/JMP relocation operands: zero on disk,
synthetic resolved targets in Ghidra. The supplied decompiler's fourteen-argument
logger prototype is incorrect for native variadic calling convention; assembly
uses RDI logger, ESI category, RDX format and normal varargs. Do not route it using
the inferred C prototype.

Next discriminator: a bounded entry/return observer around generic_reg_wait with
its actual nine-argument ABI (context, register, shift, mask, expected, delay,
tries, caller-name, caller-line), plus boot parser/link observations. Preserve the
native wait, do not shorten timeouts or invent readback success. Entry records
would identify the currently anonymous waits; a matching return only proves the
void function returned, not that polling succeeded. Avoid additional MMIO reads
until register side effects are known. No such observer is installed yet.

This narrows the evidence gap; it does not establish the first failing register,
prove reference clocks valid, or fix physical output.
