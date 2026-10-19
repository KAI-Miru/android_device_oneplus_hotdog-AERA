import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from import_vendor import graphics_inputs


class GraphicsImportTests(unittest.TestCase):
    def test_transitive_graphics_providers_come_from_the_same_dump(self):
        with TemporaryDirectory() as directory:
            dump = Path(directory)
            for name in ('vendor/lib64/egl/libEGL_adreno.so',
                         'vendor/lib64/libllvm-glnext.so', 'vendor/lib64/libgsl.so'):
                file = dump / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(b'\x7fELF' + bytes(64))
            dependencies = {'libEGL_adreno.so': ['libllvm-glnext.so', 'libc.so'],
                            'libllvm-glnext.so': ['libgsl.so', 'liblog.so'],
                            'libgsl.so': ['libion.so']}
            def info(path):
                self.assertTrue(path.is_relative_to(dump))
                return {'needed': dependencies[path.name]}
            with patch('import_vendor.elf_info', side_effect=info):
                result = graphics_inputs(dump, {'vendor/lib64/egl/libEGL_adreno.so':
                                               'vendor/lib64/egl/libEGL_adreno.so'})
            self.assertEqual(result, {
                'vendor/lib64/egl/libEGL_adreno.so': 'vendor/lib64/egl/libEGL_adreno.so',
                'system/lib64/libllvm-glnext.so': 'vendor/lib64/libllvm-glnext.so',
                'system/lib64/libgsl.so': 'vendor/lib64/libgsl.so'})

    def test_missing_graphics_dependency_cannot_fall_back_to_another_dump(self):
        with TemporaryDirectory() as directory:
            with patch('import_vendor.elf_info', return_value={'needed': ['libmissing-gpu.so']}):
                with self.assertRaisesRegex(FileNotFoundError, 'libmissing-gpu.so'):
                    graphics_inputs(Path(directory), {'vendor/lib64/egl/libEGL_adreno.so':
                                                     'vendor/lib64/egl/libEGL_adreno.so'})


if __name__ == '__main__':
    unittest.main()
