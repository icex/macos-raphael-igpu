import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/prepare-headless-lilu.py'
UPSTREAM = os.environ.get('LILU_1_6_8_SOURCE')


class HeadlessLiluPreparationTests(unittest.TestCase):
    def load_tool(self):
        spec = importlib.util.spec_from_file_location('prepare_headless_lilu', TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_patch_applies_to_pinned_source_and_drives_real_branch(self):
        if not UPSTREAM:
            self.skipTest('set LILU_1_6_8_SOURCE for pinned-source integration')
        module = self.load_tool()
        upstream = Path(UPSTREAM)
        self.assertTrue(upstream.is_dir(), 'pinned Lilu 1.6.8 source unavailable')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'Lilu-headless'
            module.prepare(upstream, output)
            source = (output / 'Lilu/Sources/kern_start.cpp').read_text()
            private = (output / 'Lilu/PrivateHeaders/kern_config.hpp').read_text()
            self.assertIn('getKernelVersion() >= KernelVersion::BigSur && !headlessInit', source)
            self.assertIn('policy.registerPolicy()', source)
            self.assertIn('bootargHeadless', private)
            self.assertIn('checkKernelArgument(bootargHeadless)', source)
            self.assertLess(source.index('checkKernelArgument(bootargFast)'),
                            source.index('headlessInit = checkKernelArgument(bootargHeadless)'))

            self.assertIn('IOLockLock(policyLock);', private)
            self.assertEqual(private.count('performInit();'), 2)

            # Compile the extracted patched registerPolicy body against tiny,
            # portable stubs so each early/policy branch is exercised.
            start = source.index('bool Configuration::registerPolicy()')
            brace = source.index('{', start)
            depth = 0
            end = None
            for index in range(brace, len(source)):
                if source[index] == '{':
                    depth += 1
                elif source[index] == '}':
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            self.assertIsNotNone(end)
            function = source[start:end].replace(
                'bool Configuration::registerPolicy()', 'bool registerPolicy()')
            harness = f'''\
#include <cassert>
enum class KernelVersion {{ BigSur = 11 }};
struct Lock {{}};
static bool alloc_ok = true;
static Lock lock_storage;
static Lock *IOLockAlloc() {{ return alloc_ok ? &lock_storage : nullptr; }}
static void IOLockFree(Lock *) {{}}
#define SYSLOG(...) do {{}} while (0)
#define DBGLOG(...) do {{}} while (0)
struct Policy {{ bool result = true; int calls = 0; bool registerPolicy() {{ ++calls; return result; }} }};
struct Configuration {{
  int version = 11; bool headlessInit = false; bool startSuccess = false;
  Lock *policyLock = nullptr; Policy policy; int early_result = 0; int early_calls = 0;
  KernelVersion getKernelVersion() {{ return static_cast<KernelVersion>(version); }}
  bool performEarlyInit() {{ ++early_calls; return early_result; }}
{function}
}};
int main() {{
  {{ Configuration c; c.early_result = 1; assert(c.registerPolicy()); assert(c.early_calls == 1 && c.policy.calls == 0 && c.startSuccess); }}
  {{ Configuration c; c.early_result = 0; assert(c.registerPolicy()); assert(c.early_calls == 1 && c.policy.calls == 1 && c.startSuccess); }}
  {{ Configuration c; c.headlessInit = true; c.early_result = 1; assert(c.registerPolicy()); assert(c.early_calls == 0 && c.policy.calls == 1 && c.startSuccess); }}
  {{ Configuration c; c.version = 10; assert(c.registerPolicy()); assert(c.early_calls == 0 && c.policy.calls == 1 && c.startSuccess); }}
  {{ Configuration c; alloc_ok = false; assert(!c.registerPolicy()); assert(c.policy.calls == 0 && c.policyLock == nullptr); alloc_ok = true; }}
  {{ Configuration c; c.policy.result = false; assert(!c.registerPolicy()); assert(c.policy.calls == 1 && c.policyLock == nullptr); }}
}}
'''
            fixture = Path(temporary) / 'register_policy.cpp'
            binary = Path(temporary) / 'register_policy'
            fixture.write_text(harness)
            subprocess.run(['c++', '-std=c++17', '-Wall', '-Werror', str(fixture), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_refuses_modified_pinned_source(self):
        if not UPSTREAM:
            self.skipTest('set LILU_1_6_8_SOURCE for pinned-source integration')
        module = self.load_tool()
        with tempfile.TemporaryDirectory() as temporary:
            source_base = Path(temporary) / 'source-base'
            shutil.copytree(Path(UPSTREAM), source_base)
            for relative in ('Lilu/Sources/kern_start.cpp', 'Lilu/PrivateHeaders/kern_config.hpp'):
                with self.subTest(relative=relative):
                    source = Path(temporary) / ('source-' + Path(relative).stem)
                    shutil.copytree(source_base, source)
                    target = source / relative
                    target.write_text(target.read_text() + '\n// changed\n')
                    with self.assertRaisesRegex(ValueError, 'pinned Lilu source hash mismatch'):
                        module.prepare(source, Path(temporary) / ('output-' + target.stem))


if __name__ == '__main__':
    unittest.main()
