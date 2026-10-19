import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from kernel_input import inspect_kernel, verify_image_kernel

class KernelInputTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(64)
        data[56:60] = b'ARMd'
        struct.pack_into('<Q', data, 16, 65536)
        return bytes(data) + b'Linux version 4.14.test (builder)\0'

    def test_supplied_bytes_and_wlan_release_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'Image'
            data = self.fixture()
            image.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            module = {'vermagic': '4.14.test SMP preempt mod_unload modversions aarch64'}
            record = inspect_kernel(image, digest, module)
            self.assertEqual(record['sha256'], digest)
            self.assertEqual(verify_image_kernel(data, image, module), record)
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                inspect_kernel(image, '0' * 64, module)
            with self.assertRaisesRegex(ValueError, 'does not contain'):
                verify_image_kernel(data + b'changed', image, module)
            with self.assertRaisesRegex(ValueError, 'WLAN module'):
                inspect_kernel(image, module_record={'vermagic': '4.14.other SMP'})

    def test_missing_or_invalid_images_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'Image'
            with self.assertRaises(FileNotFoundError): inspect_kernel(image)
            image.write_bytes(bytes(64))
            with self.assertRaisesRegex(ValueError, 'ARM64 Image'): inspect_kernel(image)

if __name__ == '__main__': unittest.main()
