import json, struct, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from boot_v2 import bootloader_layout, parse_boot, replace_ramdisk
from test_inputs import sample_boot

class BootloaderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.layout = json.loads((ROOT/'config/bootloader-layout.json').read_text())
        self.kernel = bytearray(64)
        self.kernel[56:60] = b'ARMd'
        struct.pack_into('<Q', self.kernel, 16, 47656960)

    def test_measured_working_layout_and_actual_failed_ramdisk(self):
        result = bootloader_layout(self.kernel, 32343906, 4096, self.layout)
        self.assertEqual(result['ramdisk_load_address'], 0x83826000)
        self.assertEqual(result['kernel_runtime_end'], 0x82df3000)
        with self.assertRaisesRegex(ValueError, '1253376 bytes'):
            bootloader_layout(self.kernel, 42192280, 4096, self.layout)

    def test_exact_runtime_boundary_includes_bss_and_guard_pages(self):
        self.assertEqual(bootloader_layout(self.kernel, 40939520, 4096, self.layout)['clearance_bytes'], 0)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            bootloader_layout(self.kernel, 40939521, 4096, self.layout)
        with self.assertRaisesRegex(ValueError, 'Image header'):
            bootloader_layout(bytes(64), 16, 4096, self.layout)

    def test_recompression_preserves_components_and_moves_dtbo(self):
        before = sample_boot(); original_header, original_parts = parse_boot(before)
        replacement = b'new compressed ramdisk'*200
        after = replace_ramdisk(before, replacement)
        header, parts = parse_boot(after)
        self.assertEqual(header, original_header)
        self.assertEqual(parts['ramdisk'], replacement)
        for name in ('kernel','dtb.img','recovery-dtbo.img'):
            self.assertEqual(parts[name], original_parts[name])
        self.assertEqual(struct.unpack_from('<Q', after, 1636)[0], 4*4096)

if __name__ == '__main__': unittest.main()
