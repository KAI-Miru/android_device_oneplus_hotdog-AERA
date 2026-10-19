import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_image import verify_filesystem_format_configuration


class FilesystemFormatImageTests(unittest.TestCase):
    def test_native_chooser_and_confirmation_are_required(self):
        markers = (b'Change filesystem', b'Format partition now',
                   b'Type yes to enable formatting', b'/proc/filesystems',
                   b'Unable to release userdata mapping; refusing to format.')
        binary = b'\0'.join(markers)
        self.assertFalse(verify_filesystem_format_configuration(binary)['device_format_tested'])
        for marker in markers:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                verify_filesystem_format_configuration(binary.replace(marker, b''))


if __name__ == '__main__':
    unittest.main()
