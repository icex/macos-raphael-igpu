# Stock VirtualBox publication and fence boundary

Offline source audit only; no VM start, device access, build or native changes.
This follows candidate 405's transport audit. All new source is official release
7.2.18, commit `14841851fa211c7faf615978ba385d59947236c6`, pinned by the companion
manifest. Local files reside in `run/c408-display-source`.

## What the stock paths actually acknowledge

HGSMI/VBVA flush processes command records and invokes UpdateBegin/UpdateProcess/
UpdateEnd, then releases command storage. It is not a guest-visible lease on an
immutable pixel image: `DevVGA_VBVA.cpp:352–465`. Screen resize separately hands
the connector VRAM (`:516`). Thus buffer-command completion cannot stand in for
our private snapshot ACK.

VMSVGA has a more useful source-copy boundary. `DevVGA-SVGA-cmd.cpp:8282–8355`
implements BLIT_GMRFB_TO_SCREEN by copying the bounded GMR source into the screen's
**VRAM**, then calling UpdateScreen. FIFO processing invokes that handler before
a subsequent FENCE command (`DevVGA-SVGA.cpp:6223–6250,6443–6448`). The fence writes
SVGA_FIFO_FENCE and may raise an IRQ; it does not query whether the GUI presented
or released an image. Invalid commands can return without a successful copy, so
seeing the fence alone is not proof of pixel correctness.

UpdateScreen dispatches VBVA connector calls (`DevVGA-SVGA.cpp:1772–1810`). It
neither allocates an immutable surface nor makes destination VRAM private. A
following fence can therefore support **source staging reuse after ordered copy**,
subject to successful command validation; it does not establish exclusive or
immutable destination ownership. It is not equivalent to the current sealed
presenter's stronger host-private-copy ACK contract.

The downstream GUI has two materially different paths. `UIFrameBuffer.cpp:595–614`
advertises UpdateImage for a separate-process GUI; the ordinary in-process path
does not. `DisplayImpl.cpp:909–1003` either sends NotifyUpdate(rectangle) or copies
source pixels to a SafeArray before NotifyUpdateImage. The latter copies pixels
into its locked QImage and schedules an asynchronous widget update
(`UIFrameBuffer.cpp:707–759`). This is a real host-copy opportunity, not scanout
completion; the same QImage remains mutable between updates. S_OK can also occur
without copying while updates are disallowed. A generic guest fence cannot infer
which frontend path is active or whether that branch accepted the image.

The 3D path is not a shortcut to a proven immutable contract. SurfaceDMA transfers
between guest images and host surfaces (`DevVGA-SVGA3d.cpp:695–897`); deprecated
Present dispatches surface-to-screen blits (`:1484` onward). Backend-dependent
execution/presentation and ownership require their own qualification. Enabling
VBox 3D changes the current software-only topology and is not Raphael Metal.

## Smallest honest prototype and remaining blocker

Prefer a stock **software-only source-copy discriminator**, not a fabricated
snapshot capability: on an independently prepared VMSVGA clone with an explicitly
owned FIFO and screen, define bounded staging/GMR, submit one complete BGRA image,
BLIT_GMRFB_TO_SCREEN followed by a unique fence, then poison only the source after
the fence. Verify the complete destination through an independent screenshot and
repeat with a delayed consumer. This tests source reuse. Keep SnapshotProtocol=0;
do not run the sealed snapshot presenter under a weaker ACK contract.

Before those writes, establish actual boot framebuffer service ownership and a
supported takeover. Neither port matching nor defining a GMR excludes a macOS
boot IOFramebuffer writer. A legacy VBoxVGA boot is not a VMSVGA/FIFO ownership
qualification. A first read-only guest inventory of driver/service ancestry and
BAR/device identity is smaller and safer than implementing the FIFO blindly.

The existing presenter can CPU-copy its locked SCK pixels into guest private
staging; this needs no VBox IOSurface import. Stock GMR registration requires
pinned guest pages, ordered descriptors and bounded cleanup in a guest driver.
A macOS IOSurface handle is not a VBox host surface ID or guest physical address;
this audit establishes no zero-copy IOSurface/Metal interoperability.

If retaining the exact current immutable-host-snapshot contract is mandatory,
these inspected 2D paths do not supply it. A dedicated host extension with explicit
private storage/consumer lifetime remains the direct route. This is not proof that
all stock transports are impossible: separate-process UpdateImage plus controlled
single-writer FIFO may support a useful guest-only presentation backend, but it
requires an explicitly weaker, independently tested publication contract and
frontend constraints. No host patch or guest prototype is implemented here.

Primary source links: [FIFO and screen updates](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Devices/Graphics/DevVGA-SVGA.cpp),
[GMR blit](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Devices/Graphics/DevVGA-SVGA-cmd.cpp),
[VBVA](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Devices/Graphics/DevVGA_VBVA.cpp),
[GUI framebuffer](https://github.com/VirtualBox/virtualbox/blob/14841851fa211c7faf615978ba385d59947236c6/src/VBox/Frontends/VirtualBox/src/runtime/UIFrameBuffer.cpp).
