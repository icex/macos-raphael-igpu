# The 8x8 "screen-buffer corruption" is a remote-desktop codec artifact, not a GPU defect (2026-09-14)

Boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.230 (`rgpunobin=1 rgpusdmacfg=2
rgputexdiag=2`), guest `24G830`. This closes ROADMAP item 1 and open issue 2 in `status.md`.

## The discriminating test

ROADMAP item 1 named the deciding experiment: a **lossless in-guest capture**. "If the blocks
are absent, it is the transport and this item closes."

The user, viewing the live desktop over **NoMachine**, took two screenshots ~6 minutes apart in
one session:

| File | What it is | Result |
|---|---|---|
| `remote-nomachine-client-corrupted-1944x1121.png` | KDE Spectacle screenshot of the NoMachine **client window** on the Linux host (the user's `Screenshot_20260914_163752.png`) | sparse green shards over translucent regions |
| `in-guest-lossless-clean-1280x1024.png` | macOS `screencapture` run **inside the guest** from the GUI session (`Screenshot 2026-09-14 at 16.31.46`, SHA-256 `76b2d7c5064c8f27bd022385ca95ade1724ec36bbbed0e420349d7a831575827`), pulled off the guest byte-for-byte | **clean** |

`remote-vs-inguest-comparison.png` shows them together with the shards circled.

The in-guest capture carries the guest's own framebuffer with no codec in the path (it was taken
by the user from the GUI, so it holds the Screen Recording grant that SSH-launched captures never
get). It reproduces the **same desktop content** — Safari start page, the same Favorites row, the
translucent Privacy Report card, the menu bar — and every one of those regions is pristine.

## Quantified

Saturated-green fragments (`g>170, r<130, b<130`), excluding the Dock band:

- **Remote client capture:** 29 components >= 3 px, thin diagonal shards, sub-tile aligned at
  `x%8 == 2, y%8 == 5`, scattered over the Finder sidebar, Safari favorites text, and menu bar;
  opaque interiors and bare wallpaper clean.
- **In-guest lossless capture:** 13 green components, **all legitimate UI** — three green Dock
  icons (`y ~= 966`, icon-sized 38x34), the green TripAdvisor Favorites tile (`x=314 y=562`,
  41x40), and one menu-bar status icon (`x=60 y=45`). **Zero** thin diagonal shards. The
  translucent Privacy Report card and the blurred wallpaper behind the Favorites are smooth.

## Why this is a codec signature, not GPU tiling

- The shards sit at a **2/5 sub-tile offset**, not on the origin-aligned 8x8 GFX10 micro-tile
  grid a producer/consumer tiling disagreement would follow.
- They appear **only over dithered translucency / vibrancy gradients** — exactly what a lossy
  inter-frame video codec (NoMachine's VP8/H.264) smears — and never over solid opaque fills,
  where a GPU tiling or DCC fault would corrupt equally.
- pipeBankXor was already ruled out quantitatively (<=128 px displacement, dense not sparse; the
  kernel computes no pbx at all). This capture removes the remaining GPU hypotheses (DCC /
  fast-clear stale memory) for the desktop: the framebuffer the compositor produced is correct.

The transport is not NoMachine-specific: the user reports the same shards over a **VNC** session
(Apple Screen Sharing on :5900). That is consistent, not contradictory — Apple's Screen Sharing
server and NoMachine both apply lossy compression to gradient/photographic regions by default, so
either transport smears exactly these translucent zones. A lossy transport, not a particular
product, is the cause.

## Two confounds still open, and the one clean test that closes them

The in-guest lossless capture is dispositive *for the frame it captured*, but two gaps remain:

1. **Same-frame timing.** The clean in-guest shot (16:31:46, 1280x1024) and the corrupted client
   shots are different frames minutes apart at different resolutions (a Displays pane was in use
   between them). The shards are sparse and may be intermittent, so a clean snapshot does not by
   itself prove a *simultaneously* corrupted frame was clean in the framebuffer.
2. **Was the VNC lossless?** If the user's VNC path were already lossless and still showed shards,
   the transport explanation would fail. Apple Screen Sharing defaults to adaptive (lossy), so
   this is unlikely, but it is unconfirmed.

**Decisive confirming test (next GPU desktop session):** capture one artifacted frame two ways at
once — a **forced-lossless / raw-encoding VNC** grab (TigerVNC `-PreferredEncoding=Raw
-AutoSelect=0 -FullColour`, or `-QualityLevel 9 -CompressLevel 0`) and an **in-guest
`screencapture`** of the same moment. If the raw-VNC frame is clean while the normal lossy view
shows shards, the transport is confirmed beyond any doubt. If the raw-VNC frame *still* shows
shards, the framebuffer is implicated and this reopens as a GPU/compositor question.
`tools/vnc-frame-capture.py` is the scripted path; force raw encoding on it before the run.

## Consequence (pending the confirming test)

On the evidence so far there is **very likely no GPU rendering bug** — the compositor's
framebuffer for the captured frame is correct, and the fragment geometry is codec-shaped. To
*watch* the desktop without artifacts, use a lossless transport (raw-encoding VNC, or max
NoMachine quality) or wire the AMD scanout to a presentable surface (ROADMAP item 3), which
removes the remote codec from the path entirely.
