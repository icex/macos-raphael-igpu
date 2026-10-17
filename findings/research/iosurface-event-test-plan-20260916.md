# Next cross-process GPU-event test — reviewed transport plan

Preparation only; no additional GPU exposure or positive event-sharing claim.
The preceding IOSurface test proves host-ordered visibility, not GPU-only events.

Apple's [MTLSharedEventHandle documentation](https://developer.apple.com/documentation/metal/mtlsharedeventhandle?language=objc)
specifies newSharedEventHandle, transport through XPC, then
newSharedEventWithHandle: in the receiving process. NSSecureCoding conformance
alone is not evidence that a normal NSKeyedArchiver NSData pipe preserves the
underlying transferable rights. The byte-archive draft was rejected before build
or hardware testing and removed from the repository.

Use an NSXPC connection with a typed protocol that transfers the handle object
itself; restrict accepted classes and validate the connection's peer identity.
A temporary launchd-managed user service or bundled XPC helper supplies the
bootstrap channel. Keep service identity, lifetime and teardown explicit; avoid a
persistent installation or global Mach service name collision. First validate
connection and handle import, without queuing GPU waits. A failed transfer is a
test-infrastructure failure, not an iGPU synchronization defect.

For each bounded round, the consumer imports the same IOSurface and Metal registry
ID, encodes an event wait before opening its blit encoder, then copies to managed
readback, synchronizes and commits. Only after commit does it acknowledge SUBMITTED.
The producer then uploads a unique pixel pattern, ends its blit encoder, encodes
GPU event signal and commits. No CPU writes to signaledValue and no producer
completion before consumer submission. The consumer waits with a deadline and
checks every active pixel; completion handlers are installed before commit.
Host round acknowledgments serialize buffer reuse, not the producer→consumer GPU
memory dependency. Require normal child exit and separately verify VM cleanup.

An event wait that remains blocked after process termination could affect engine
progress; preserve all existing capture, host-fault, deadline and recovery paths.
Do not turn a missing GPU completion into a host-side signal to pass the test.
The smallest first exposure is one imported event and one consumer-first round;
expand only after correct output and cleanup.
