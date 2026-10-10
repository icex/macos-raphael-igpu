# Candidate435: independent native framebuffer bundle

434 proved that adding IOGraphicsFamily to the early Lilu GPU plugin prevents its
load: macOS reports missing library0xdc00800e even without new framebuffer code.
435 restores the GPU plugin's original dependency set and exact432 source digest.
It must first pass its baseline probe; the new framebuffer is not part of this card's
boot injection or functional arguments.

The native prototype from433 is preserved under `native-framebuffer/`, with its
own as.rgpu.RaphaelFramebuffer identity, IOFramebuffer/PCI/KPI dependencies and
Console loading requirement. `tools/build-native-framebuffer.py` cross-builds it
independently. It does not compile Lilu plugin_start.cpp or import Lilu symbols.
Standard x86_64 libkmod _start/_stop wrappers call the bundle-specific entry points;
compiler-generated metaclass initializer sections remain intact. The entry logs
an exact build ID. Module unload intentionally returns failure until qualified;
IOService partial-start/stop/free still tear down timer resources.

Do not manually call the historical i386/PPC C++ initializer implementation.
The pinned SDK's IOFramebuffer size0x1d0 matches actual24G830 MetaClass allocation;
all88 IOFramebuffer imports exist as external symbols in the KDK. This does not
prove guest kernel-collection resolution, virtual-table compatibility or loading.

After baseline probe completion, install the native-aware external launcher guard
while preserving the capture-app seal, then inspect actual loaded graphics bundles,
on-disk libraries, SIP and kernel-collection/KDK availability. Select runtime load
or separate boot injection based on those observations. Loading/matching requires
its own identity evidence and does not qualify120FPS delivery. No stale cache
deletion, broad permission changes or framebuffer segment-protection changes are
authorized by this plan.

The native code still requires opt-in probe, exclusive framebuffer/mode ownership,
real Retina enumeration and VBL measurements.32MiB transport excludes5K;431's64MiB
prototype and dynamic modes remain separate incomplete work.
