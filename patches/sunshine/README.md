# Sunshine VideoToolbox capture lock patch

`v2026.914.233613-gpu-capture-lock.patch` targets the pinned Sunshine source
snapshot/tag `2026.914.233613`. Apply from the upstream repository root:

```sh
sha256sum src/platform/macos/av_img_t.h src/platform/macos/display.mm
patch -p1 < patches/sunshine/v2026.914.233613-gpu-capture-lock.patch
```

The fetched review snapshot is flattened for analysis; its equivalent files
were validated with `patch --dry-run -p4`.

Expected original hashes for the reviewed snapshot are:

```text
av_img_t.h  0ef326af6a53d31ba478b2bbee18653c367ce16ef4fd407426300f94ff459dbc
display.mm  f5dc57e119120b4bae6dbc78422f80afa4dc8cfee956c25270143d0eafb28921
```

The patch elides CPU base-address locking only for an atomic, explicitly selected
VideoToolbox NV12/P010 zero-copy path and additionally checks the actual captured
CVPixelBuffer format. Software, unknown, and failed-lock paths retain CPU
locking; capture and dummy-image callbacks propagate lock failure instead of
exposing a null CPU pointer. Each wrapper records its own lock decision, while
`nv12_zero_device` retains the CVPixelBuffer through its AVBufferRef.

Source-reviewed only: not built, live-tested, or deployed. Validate the original
file hashes before applying.

References: [CVPixelBufferLockBaseAddress](https://developer.apple.com/documentation/corevideo/cvpixelbufferlockbaseaddress(_:_:)) and [managed Metal resource synchronization](https://developer.apple.com/documentation/metal/synchronizing-a-managed-resource-in-macos).

This targets [Sunshine’s GPL-3.0 source](https://github.com/LizardByte/Sunshine/tree/v2026.914.233613); upstream context retains its license. The patch is not part of the kext build.
