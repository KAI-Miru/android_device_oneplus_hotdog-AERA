import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_image import verify_gpu_startup_configuration


class GpuStartupTests(unittest.TestCase):
    renderer = (b'/system/lib64/libnativewindow.so\0'
                b'ro.aera.gpu.required_libraries\0'
                b'GPU runtime: required library unavailable: %s\0')
    properties = b'ro.aera.gpu.required_libraries=/system/lib64/libllvm-glnext.so\n'

    def entries(self):
        profile = json.loads((ROOT / 'tools/gpu-source.json').read_text())
        entries = {name: (0o100644, b'runtime') for name in
                   set(profile['seeds'].values()) | set(profile['required_libraries'])}
        entries['vendor/etc/init/aera-gralloc.rc'] = (0o100644,
            b'service aera-gralloc /system/bin/aera-vendor-allocator\n'
            b'    setenv LD_LIBRARY_PATH /system/lib64:/vendor/lib64:/vendor/lib64/egl\n')
        return entries

    def test_complete_ramdisk_runtime_needs_no_vendor_mount(self):
        report = verify_gpu_startup_configuration(self.renderer, self.properties, self.entries())
        self.assertFalse(report['vendor_mount_before_ui'])
        self.assertFalse(report['installed_vendor_required'])
        self.assertFalse(report['cold_boot_tested'])

    def test_missing_dynamic_gpu_input_is_rejected(self):
        for name in self.entries():
            if name.endswith('.rc'): continue
            with self.subTest(file=name):
                entries = self.entries()
                del entries[name]
                with self.assertRaisesRegex(ValueError, 'Missing ramdisk GPU runtime'):
                    verify_gpu_startup_configuration(self.renderer, self.properties, entries)

    def test_installed_vendor_workaround_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'pins the installed vendor'):
            verify_gpu_startup_configuration(self.renderer + b'Native UI: vendor runtime mount unavailable',
                                             self.properties, self.entries())

    def test_missing_preflight_is_rejected(self):
        for marker in (b'ro.aera.gpu.required_libraries\0', b'GPU runtime: required library unavailable'):
            with self.assertRaises(ValueError):
                verify_gpu_startup_configuration(self.renderer.replace(marker, b''), self.properties, self.entries())
        with self.assertRaises(ValueError):
            verify_gpu_startup_configuration(self.renderer, b'', self.entries())

    def test_external_compiler_requirement_is_rejected(self):
        for name in (b'libllvm-qgl.so', b'libllvm-qcom.so'):
            entries = self.entries()
            entries['system/lib64/libllvm-glnext.so'] = (0o100644, name)
            with self.assertRaisesRegex(ValueError, 'external compiler'):
                verify_gpu_startup_configuration(self.renderer, self.properties, entries)

    def test_allocator_cannot_prefer_installed_vendor_providers(self):
        entries = self.entries()
        name = 'vendor/etc/init/aera-gralloc.rc'
        entries[name] = (0o100644, entries[name][1].replace(
            b'/system/lib64:/vendor/lib64:/vendor/lib64/egl', b'/vendor/lib64:/system/lib64'))
        with self.assertRaisesRegex(ValueError, 'allocator must prefer'):
            verify_gpu_startup_configuration(self.renderer, self.properties, entries)


if __name__ == '__main__':
    unittest.main()
