# Candidate 418: production build of transactional VFIO DMA changes

This is an offline build and bounded non-VM fault-injection test. It does not open VFIO, launch VirtualBox, install binaries, or modify host modules.

## Inputs and isolation

Fresh candidate 418 was created from fetched dev `0ecc171` and merged the [verified candidate 416 baseline](virtualbox-isolated-baseline-build-20261010.md), commit `bcc482b`. An independent reflink copy of its official 7.2.18 source was made under `run/c418-build/VirtualBox-7.2.18`. The copied output directory was removed and configure regenerated with the new absolute source path, so no old objects can stand in for a production compile.

The combined 411/413 patch applies with `patch -p1 --fuzz=0`. Initial patch SHA256: `602c74238a7f74a4f789bb690c5bb58e9701d8f57f0b9955367075eb779b92c2`; final patch including the compatibility-header correction: `77a06cedfd8e384becc7e4c15ac56a427dab3ee7437df75a811465921bfc8646`. Patched release `src/VBox/Devices/Bus/DevPciVfio.cpp` SHA256: `6c635c3d2d18720e8ed9f12bb34166a57a07c4a2b7499a66f88896a7dc3a6104`. Expanded release `$Id$` metadata does not intersect the changed hunks.

Configure options and signed user-local dependencies are identical to 416. Main/XPCOM, headless, device libraries and VFIO remain enabled; optional Qt/OpenGL, kernel-module build, docs, Java/Python/SDL/extpack and additions packaging remain disabled. `kmk -j8` runs only in the independent tree.

## Validation

The initial full build exited 2 in `pciVfioUnmapRegion`: production uses bundled `DevPciVfio.h`, which lacked `vfio_iommu_type1_dma_unmap`, `iommu_ioas_unmap` and their ioctl constants. The extracted fixture had used system Linux headers and therefore missed this integration error. Original `build.log` is retained.

The patch now adds Linux-compatible fixed request definitions to the bundled header. The VFIO structure intentionally includes only the fixed prefix because rollback uses flags zero and no dirty-bitmap tail. A new compiled test extracts these exact production additions and compares struct sizes, alignment, every field offset and ioctl values against Linux UAPI. Both this test and the transaction matrix pass. The resumed full build is recorded independently in `build-fixed.log`; it exited 0. VBoxDD, VBoxVMM, Main/XPCOM, VBoxSVC, VBoxManage and VBoxHeadless linked successfully, and 242 testcase executable files were built. They were not executed. Shared-library dependencies resolve for the principal userland outputs. The final patch was reapplied to clean baseline files with zero fuzz; both resulting source files are byte-identical to the compiled files.

`python3 -B -m unittest discover -s tests -p test_vbox_dma_transaction.py -v` passed the compiled transaction fixture. It compiles the exact patch functions and BME branch with PGM/ioctl substitutes. Both legacy VFIO and IOMMUFD paths cover first/middle/final map failure, allocation failure, reverse rollback, failed/short unmap and sticky refusal. Empty RAM, reserved/unexpected page errors and BME suppression use the default legacy fixture. `pciVfioMapRegion` is substituted: the test does not execute its production map-ioctl branches. It is one Python test driving a C++ fault matrix, not a real PGM or IOMMU test.

The complete candidate 418 host suite passed: 1,488 tests, 8 skipped, 56.376 seconds. This branch is based on published dev `0ecc171`; independently active candidate changes are not included.

## Remaining boundary

Full-source compilation closes the callback/API compatibility gap only. This code still releases temporary page mappings and discovers RAM by scanning; it does not pin the meaning of a guest physical address across ballooning, reset, MMIO overlap or state load. No physical run is admitted by this result. [The proposed first PGM lease slice](virtualbox-pgm-lease-prototype-plan-20261010.md) identifies authoritative enumeration and the disposition boundaries that must be enforced, with an unconnected software lease test before VFIO integration.

Evidence: [build and test artifact hashes](virtualbox-dma-production-build-evidence-20261010.json). Original and corrected build logs remain separate; no failed receipt was rewritten.
