# Candidate 415: opt-in root relay readiness probe

Offline implementation, not native-qualified. The controller's explicit
`--root-relay` option adds virtio NAT and localhost reachability while retaining
3D off, no physical GPU, the existing exact-VM ownership/cleanup and 300-second
ceiling. Default NIC remains none. GUI stays enabled; boot framebuffer suppression
must wait for demonstrated driver/DHCP/root-daemon communication. This option
cannot be combined with the exchange disk experiment.

The relay binds exclusively to 127.0.0.1:8888 before VM creation; an occupied port
fails without taking over its service. It serves one fixed read-only command on
/cmd, then empty commands. It accepts one bounded /out result with exact generated
nonce markers, UID0 and an 8 MiB ceiling. POST reads have a three-second whole-body
budget, also bounded by the original controller deadline. No arbitrary commands,
shutdown, clipboard, TCC or guest writes are provided by this payload. The existing
root polling agent itself writes its normal /tmp/agent.out; it is not replaced.

Before command or result acceptance the controller verifies unchanged scope bytes,
exact UUID/config running state and one owned VBox process with matching --startvm,
executable name and pinned PID/start ticks. Only sanitized scope/payload hash and
private result bytes are retained. Nonce markers associate an observation; they
are **not authentication** of a guest over loopback. Local processes can access
the listener. NAT also allows outbound networking; localhost reachability is not
an egress-isolation policy. No other active guest should poll this fixed port.

The fixed payload reports UID, guest boot UUID/build, interfaces, AppleVirtIONetwork
and IOFramebuffer trees. AppleVirtIO's local 24G830 personality declares network
type1/vendor1af4; VBox7.2.18 supplies a transitional network device. These are
source compatibility clues only. Actual driver attachment, DHCP, daemon startup
and a correct nonce response remain unproven. Existing root daemon ownership must
be checked from captured evidence rather than inferred from agent-server.py.

Root can prepare bootH independent derivatives of stopped bootG, then use the
existing controller command with --graphics-controller vmsvga --root-relay,
RealTSCOffset and eight CPUs. Keep normal GUI shutdown; relay shutdown is absent.
A missing result is a failed readiness probe, not permission to suppress graphics.

Software tests use real loopback HTTP to check port collision, wrong endpoints,
invalid nonce/UID framing, oversized input, expired/changed scope, one command and
one accepted result. No native network/VM/device operations have been performed.
