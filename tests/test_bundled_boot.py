import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kernel_input import COMPONENTS, verify_bundled_boot


class BundledBootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'prebuilt').mkdir()
        (self.root / 'modules').mkdir()
        self.write_fixture()

    def tearDown(self):
        self.temp.cleanup()

    def write_fixture(self, lzma=True):
        header = bytearray(4096); header[:8] = b'ANDROID!'
        struct.pack_into('<I', header, 36, 4096)
        struct.pack_into('<I', header, 40, 2)
        kernel = bytearray(64); kernel[56:60] = b'ARMd'
        config = b'CONFIG_RD_LZMA=y\n' if lzma else b'# CONFIG_RD_LZMA is not set\n'
        kernel = bytes(kernel) + b'Linux version 4.14.fixture\0IKCFG_ST' + gzip.compress(config) + b'IKCFG_ED'
        data = dict(zip(COMPONENTS, (bytes(header), kernel, b'reference ramdisk', b'dtbo', b'dtb')))
        payload = data[COMPONENTS[0]] + b''.join(data[n] + bytes((-len(data[n])) % 4096) for n in COMPONENTS[1:])
        manifest = {'files': {}, 'source_sha256': 'a' * 64, 'source_ramdisk_imported': False,
                    'stock_boot_payload_bytes': len(payload), 'stock_boot_payload_sha256': hashlib.sha256(payload).hexdigest()}
        for name, blob in data.items():
            (self.root / 'prebuilt' / name).write_bytes(blob)
            manifest['files'][name] = {'bytes':len(blob), 'sha256':hashlib.sha256(blob).hexdigest()}
        (self.root / 'prebuilt/manifest.json').write_text(json.dumps(manifest))
        module = b'original module fixture'
        (self.root / 'modules/qca_cld3_wlan.ko').write_bytes(module)
        record = {'vermagic':'4.14.fixture SMP', 'bytes':len(module), 'sha256':hashlib.sha256(module).hexdigest()}
        (self.root / 'modules/manifest.json').write_text(json.dumps({'matching_boot_sha256':'a'*64, 'files':{'qca_cld3_wlan.ko':record}}))

    def test_bundled_inputs_ignore_external_kernel_environment(self):
        with patch.dict(os.environ, {'AERA_PREBUILT_KERNEL':'/missing/external/Image'}):
            self.assertEqual(verify_bundled_boot(self.root)['release'], '4.14.fixture')

    def test_tampering_any_component_or_module_is_rejected(self):
        for name in COMPONENTS:
            path = self.root / 'prebuilt' / name; old = path.read_bytes()
            path.write_bytes(old + b'changed')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'identity differs'):
                verify_bundled_boot(self.root)
            path.write_bytes(old)
        (self.root / 'modules/qca_cld3_wlan.ko').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'module identity'):
            verify_bundled_boot(self.root)

    def test_stock_payload_provenance_and_native_ramdisk_boundary_are_checked(self):
        path = self.root / 'prebuilt/manifest.json'; original = json.loads(path.read_text())
        for change in ({'stock_boot_payload_sha256':'0'*64}, {'source_ramdisk_imported':True}):
            path.write_text(json.dumps(dict(original, **change)))
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_bundled_boot(self.root)

    def test_missing_kernel_compression_support_or_matching_module_is_rejected(self):
        self.write_fixture(lzma=False)
        with self.assertRaisesRegex(ValueError, 'LZMA'):
            verify_bundled_boot(self.root)
        self.write_fixture()
        path = self.root / 'modules/manifest.json'; manifest = json.loads(path.read_text())
        manifest['files']['qca_cld3_wlan.ko']['vermagic'] = '4.14.other SMP'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'WLAN module'):
            verify_bundled_boot(self.root)

    def test_real_original_f22_set_and_fixed_board_kernel(self):
        record = verify_bundled_boot(ROOT)
        self.assertEqual(record['release'], '4.14.180-perf+')
        self.assertEqual(record['sha256'], 'df645d4cfa3173530ce59aa59170a416a2fb408c42de06784ec3f42a60e32347')
        profile = json.loads((ROOT / 'config/device.json').read_text())
        self.assertEqual(profile['kernel']['sha256'], record['sha256'])
        self.assertEqual(profile['kernel']['release'], record['release'])
        self.assertTrue(profile['kernel']['tracked'])
        board = (ROOT / 'BoardConfig.mk').read_text()
        self.assertIn('TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilt/kernel', board)
        self.assertNotIn('AERA_PREBUILT_KERNEL', board)
        for name in ('device.mk', 'Android.mk'):
            self.assertNotIn('ramdisk-stock.cpio.gz', (ROOT / name).read_text())


if __name__ == '__main__':
    unittest.main()
