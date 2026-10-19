import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_wifi import verify_module


class WifiModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (ROOT / 'modules/qca_cld3_wlan.ko').read_bytes()
        cls.record = json.loads((ROOT / 'modules/manifest.json').read_text())['files']['qca_cld3_wlan.ko']

    def test_pinned_module_matches_recorded_abi(self):
        info = verify_module(self.data, self.record)
        self.assertEqual(info['depends'], '')

    def test_changed_module_and_wrong_kernel_abi_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            verify_module(self.data[:-1] + bytes([self.data[-1] ^ 1]), self.record)
        record = dict(self.record, vermagic='4.14.357-ColorOS15-ci58+')
        with self.assertRaisesRegex(ValueError, 'kernel ABI'):
            verify_module(self.data, record)

    def test_module_with_wrong_elf_architecture_is_rejected(self):
        data = self.data[:18] + (40).to_bytes(2, 'little') + self.data[20:]
        record = dict(self.record, sha256=hashlib.sha256(data).hexdigest())
        with self.assertRaisesRegex(ValueError, 'ARM64'):
            verify_module(data, record)


if __name__ == '__main__':
    unittest.main()
