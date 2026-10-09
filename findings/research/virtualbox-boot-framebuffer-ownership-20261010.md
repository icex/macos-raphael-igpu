# VirtualBox boot framebuffer ownership: configuration discriminator

Offline source analysis, candidate 412; no VM or device access. Candidate 409's
actual screenshot identifies Display_boot / IONDRVFramebuffer as active. Full PCI
ancestry remains pending exchange-disk extraction in candidate 410.

The matching 24G830 decoded IONDRVSupport probe at 0x1676 queries provider property
`AAPL,iokit-ignore-ndrv`. Its assembly calls the provider vtable at +0x2b8, tests
the returned pointer at 0x169c, and returns zero at 0x16a1 when non-null. Only the
absent-property path reaches the superclass probe at 0x16b2. The decompiler's
string and branch interpretation agree with pinned Apple's open source
IONDRVFramebuffer::probe. Property presence is tested, not its boolean value:
setting a false/zero property would still suppress this probe in these sources.
This is a supported configuration entry point in the inspected driver; no Apple
binary modification is needed for the proposed discriminator.

The 24G830 IOBootNDRV::fromRegistryEntry at 0x2fae obtains boot console geometry,
searches provider memory descriptors for the console physical address and creates
a subrange of rowbytes times height. The open-source implementation matches this
structure. Thus an independent presentation writer cannot treat existing boot
framebuffer memory as unowned just because no SVGA-specific accelerated driver
was found. Suppressing a future probe also does not revoke an already running
framebuffer or its user mappings; changing the property during a live session is
not a safe takeover method.

Next bounded discriminator, after actual PCI-path discovery: use a fresh isolated
loader clone to inject the property before driver matching at the exact VMSVGA
provider. Retain the original loader. Use an independently prepared launch job
and small exchange disk to capture IOService/IOFramebuffer state even if visible
boot output remains frozen. Require both property presence at the correct
provider and absence of the prior framebuffer's attachment, plus continued guest
execution. Also inspect descendants and IODeviceTree matching; PCI ancestry alone
must not hide another display nub. The experiment must not write FIFO/registers,
claim exclusive ownership, or run the sealed snapshot presenter.

A later presentation driver still needs explicit provider ownership, its own
bounded memory/FIFO lifecycle and verified absence of another writer. Boot console
writes, panic console output and Apple display matching must be considered.
Suppressing IONDRVFramebuffer alone is not an exclusive framebuffer lease and
provides no Metal acceleration. The original stronger snapshot ACK remains
unadvertised for stock VBox transports.

Evidence: companion JSON hashes eight matching decoded C/assembly files and the
pinned open-source file. Primary reference:
[Apple IONDRVFramebuffer](https://github.com/apple-oss-distributions/IOGraphics/blob/76285384ff0ce63965a21b8023bf6d7e447fcc19/IONDRVSupport/IONDRVFramebuffer.cpp).
