import struct
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_wifi import verify_module_metadata_tool


def elf(machine=183):
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    return ident + struct.pack('<HHIQQQIHHHHHH', 3, machine, 1, 0, 0, 0, 0,
                               64, 56, 0, 64, 0, 0) + b'modinfo\0'


class ModuleReaderTests(unittest.TestCase):
    def test_bundled_reader_can_be_native_or_toybox_link(self):
        verify_module_metadata_tool({'system/bin/modinfo': (0o100755, elf())})
        verify_module_metadata_tool({'system/bin/modinfo': (0o120777, b'toybox'),
                                    'system/bin/toybox': (0o100755, elf())})

    def test_missing_unexecutable_or_wrong_architecture_reader_is_rejected(self):
        for entries in ({}, {'system/bin/modinfo': (0o100644, elf())},
                        {'system/bin/modinfo': (0o100755, elf(62))},
                        {'system/bin/modinfo': (0o120777, b'../../foreign')},
                        {'system/bin/modinfo': (0o120777, b'toybox')},
                        {'system/bin/modinfo': (0o120777, b'toybox'),
                         'system/bin/toybox': (0o100755, elf().replace(b'modinfo', b'no_info'))}):
            with self.subTest(entries=list(entries)), self.assertRaises(ValueError):
                verify_module_metadata_tool(entries)


if __name__ == '__main__':
    unittest.main()
