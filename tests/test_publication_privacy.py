import importlib.util
from pathlib import Path
import plistlib
import unittest

SOURCE = Path(__file__).resolve().parents[1]/'tools/privacy-check.py'
spec = importlib.util.spec_from_file_location('publication_privacy', SOURCE)
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


class PublicationPrivacyTests(unittest.TestCase):
    def test_personal_paths_and_key_material_are_rejected_without_values_in_report(self):
        path = ('/' + 'home/' + 'personal-account/project').encode()
        key = ('-----BEGIN ' + 'PRIVATE KEY-----').encode()
        self.assertEqual(privacy.inspect_content('capture.txt', path + b'\n' + key),
                         {'personal home path', 'private-key header'})

    def test_generic_paths_and_documentation_network_examples_are_allowed(self):
        data = b'/home/user/project /home/arch/OSX-KVM /Users/runner/build 192.0.2.10 10.0.2.2 52:54:00:12:34:56'
        self.assertEqual(privacy.inspect_content('example.txt', data), set())

    def test_actual_local_network_and_device_addresses_are_rejected(self):
        data = ('.'.join(['192', '168', '20', '3']) + ' ' +
                ':'.join(['00', '11', '22', '33', '44', '55'])).encode()
        self.assertEqual(privacy.inspect_content('capture.txt', data),
                         {'local network address', 'device MAC address'})

    def test_populated_machine_identity_is_rejected_and_empty_template_allowed(self):
        data = plistlib.dumps({'PlatformInfo': {'Generic': {'SystemSerialNumber': 'EXAMPLE12345'}}})
        self.assertEqual(privacy.inspect_content('config.plist', data), {'populated OpenCore identity'})
        data = plistlib.dumps({'PlatformInfo': {'Generic': {'SystemSerialNumber': ''}}})
        self.assertEqual(privacy.inspect_content('template.plist', data), set())


if __name__ == '__main__':
    unittest.main()
