import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_image import verify_filesystem_format_configuration


class FilesystemFormatImageTests(unittest.TestCase):
    MARKERS = (b'Change filesystem', b'Format partition now',
               b'Type yes to enable formatting', b'/proc/filesystems',
               b'dmctl delete userdata',
               b'userdata mapping removal failed or was not confirmed; refusing to format.')

    def binary(self):
        return b'\0'.join(self.MARKERS)

    def entries(self, mode=0o100755, machine=183):
        ident = b'\x7fELF\x02\x01\x01' + bytes(9)
        elf = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, machine, 1,
                          0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
        return {'system/bin/dmctl': (mode, elf)}

    def test_native_chooser_confirmation_and_checked_cleanup_are_required(self):
        binary = self.binary()
        report = verify_filesystem_format_configuration(binary, self.entries())
        self.assertFalse(report['device_format_tested'])
        self.assertEqual(report['mapping_cleanup_command'], 'dmctl delete userdata')
        for marker in self.MARKERS:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                verify_filesystem_format_configuration(binary.replace(marker, b''), self.entries())

    def test_obsolete_guard_message_cannot_stand_in_for_current_cleanup(self):
        binary = self.binary().replace(self.MARKERS[-1],
                 b'Unable to release userdata mapping; refusing to format.')
        with self.assertRaises(ValueError):
            verify_filesystem_format_configuration(binary, self.entries())

    def test_forced_removal_is_rejected_even_with_all_other_markers(self):
        with self.assertRaisesRegex(ValueError, 'non-forced'):
            verify_filesystem_format_configuration(
                self.binary() + b'\0dmsetup remove -f userdata', self.entries())

    def test_mapping_tool_must_be_present_executable_and_arm64(self):
        for entries in ({}, self.entries(mode=0o100644),
                        self.entries(mode=0o120777), self.entries(machine=62)):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                verify_filesystem_format_configuration(self.binary(), entries)


if __name__ == '__main__':
    unittest.main()
