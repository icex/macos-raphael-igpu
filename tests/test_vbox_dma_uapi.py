"""Compare the patch's production compatibility definitions with Linux UAPI."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DmaUapiTests(unittest.TestCase):
    def test_production_unmap_abi_matches_linux(self):
        compiler = shutil.which('c++')
        if not compiler or not Path('/usr/include/linux/iommufd.h').exists():
            self.skipTest('C++ compiler and Linux IOMMUFD UAPI required')
        patch = (ROOT / 'findings/research/patches/virtualbox-7.2.18-vfio-dma-transaction.patch').read_text()
        header = patch.split('+++ b/src/VBox/Devices/Bus/DevPciVfio.h\n', 1)[1]
        definitions = '\n'.join(line[1:] for line in header.splitlines() if line.startswith('+'))
        definitions = definitions.replace('IOMMU_IOAS_UNMAP', 'COMPAT_IOMMU_IOAS_UNMAP')
        definitions = definitions.replace('VFIO_IOMMU_UNMAP_DMA', 'COMPAT_VFIO_IOMMU_UNMAP_DMA')
        prefix = '''#include <cstdint>
#include <cstddef>
#include <linux/vfio.h>
#include <linux/iommufd.h>
#define AssertCompileSize(t,n) static_assert(sizeof(t)==(n), "compat size")
namespace compat {
'''
        assertions = ['}\nstatic_assert(COMPAT_IOMMU_IOAS_UNMAP == IOMMU_IOAS_UNMAP, "ioas ioctl");',
                      'static_assert(COMPAT_VFIO_IOMMU_UNMAP_DMA == VFIO_IOMMU_UNMAP_DMA, "vfio ioctl");']
        for struct, fields in [('iommu_ioas_unmap', ['size', 'ioas_id', 'iova', 'length']),
                               ('vfio_iommu_type1_dma_unmap', ['argsz', 'flags', 'iova', 'size'])]:
            assertions += [f'static_assert(sizeof(compat::{struct}) == sizeof(::{struct}), "size");',
                           f'static_assert(alignof(compat::{struct}) == alignof(::{struct}), "alignment");']
            for field in fields:
                assertions.append(f'static_assert(offsetof(compat::{struct}, {field}) == offsetof(::{struct}, {field}), "offset");')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'abi.cpp'
            source.write_text(prefix + definitions + '\n' + '\n'.join(assertions) + '\nint main() {}\n')
            result = subprocess.run([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(Path(directory) / 'abi')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
