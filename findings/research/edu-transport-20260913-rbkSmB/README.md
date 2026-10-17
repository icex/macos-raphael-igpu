# CPU-only GDB physical MMIO transport evidence

Captured from `/tmp/edu-probe-parent-rbkSmB` and preserved without hardware GPU exposure.
The complete result records `gdb_mode=1`, QMP `prelaunch` with `running=false`, and
an EDU test device with a 1 MiB BAR at guest physical `0x10000000`. The reversible
MMIO test read `0x00000000`, observed the inverted value `0x87a9cbed`, and restored
`0x00000000`. This proves only the bounded physical MMIO transport path; it is not
Raphael GPU recovery evidence and does not authorize a GPU launch.

The run's Docker CID was `f76008c8d1d5b9a6f373818d3c9db001b522de455b1874dc4f77234f8d2178db`.
The parent verified that `docker inspect` no longer finds it. Eight unit tests passed.
