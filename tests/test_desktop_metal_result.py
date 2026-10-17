import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesktopMetalResultTests(unittest.TestCase):
    RUN = 'a' * 32

    def output(self, **changes):
        result = dict(run_id=self.RUN, passed=True, device='AMD Radeon Navi23', metal3=True,
                      registry_id=4294968084, completed_command_buffers=1, values_checked=1,
                      displays=[], display_on_device=False,
                      windowserver_accelerator_client=True,
                      accelerators=[dict(registry_id=4294968084, same_as_metal_device=True,
                                         user_clients=['pid 162, WindowServer'])])
        result.update(changes)
        return 'RGPU_DESKTOP_METAL_RESULT ' + json.dumps(result) + '\n\nRGPU_EXIT ' + self.RUN + ' 0\n'

    def test_valid_result_and_evidence(self):
        tool = load('desktop-metal-test')
        result = tool.validate_output(self.output(), self.RUN)
        evidence = tool.desktop_evidence(result)
        self.assertTrue(evidence['windowserver_accelerator_client'])
        self.assertEqual(evidence['device_clients'], ['pid 162, WindowServer'])

    def test_rejects_wrong_device_stale_nonce_and_failed_exit(self):
        tool = load('desktop-metal-test')
        with self.assertRaises(ValueError):
            tool.validate_output(self.output(device='Other'), self.RUN)
        with self.assertRaises(ValueError):
            tool.validate_output(self.output(run_id='b' * 32), self.RUN)
        with self.assertRaises(ValueError):
            tool.validate_output(self.output().replace(' 0\n', ' 1\n'), self.RUN)
        with self.assertRaises(ValueError):
            tool.validate_output(self.output(values_checked=0), self.RUN)

    def test_runner_and_classifier_know_the_profile(self):
        experiment = (ROOT / 'tools/experiment.py').read_text()
        self.assertIn("'desktop-metal': {", experiment)
        self.assertIn("'source': 'tests/desktop_metal_probe.m',", experiment)
        classifier = (ROOT / 'tools/classify-run.py').read_text()
        self.assertIn("'desktop-metal': 'desktop-metal-test.py'", classifier)
        self.assertIn("'RGPU_DESKTOP_METAL_RESULT '", classifier)
        self.assertTrue((ROOT / 'tests/desktop_metal_probe.m').is_file())


if __name__ == '__main__':
    unittest.main()
