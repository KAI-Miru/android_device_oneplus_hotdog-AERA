import copy
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_hotdog import verify_device_configuration, verify_fastboot_runtime, verify_fstab, verify_health_runtime, verify_health_startup


class HotdogTests(unittest.TestCase):
    def test_native_device_configuration(self):
        result = verify_device_configuration(ROOT)
        self.assertEqual(result['recovery_partition'],'recovery')

    def entries(self):
        ident = b'\x7fELF\x02\x01\x01'+bytes(9)
        elf = struct.pack('<16sHHIQQQIHHHHHH',ident,2,183,1,0,0,0,0,64,0,0,0,0,0)
        return {'system/bin/fastbootd':(0o100755,elf),
                'init.recovery.qcom.rc':(0o100644, (ROOT/'recovery/root/init.recovery.qcom.rc').read_bytes()),
                'system/etc/init/android.hardware.health@2.1-service.rc':(0o100644,
                    b'service health-hal-2-1 /system/bin/android.hardware.health@2.1-service\n    disabled\n'),
                'system/bin/android.hardware.health@2.1-service':(0o100755,elf),
                'system/lib64/hw/android.hardware.health@2.0-impl-2.1.so':(0o100644,elf),
                'vendor/etc/vintf/manifest/android.hardware.health@2.1.xml':(0o100644,
                    b'<manifest type="device"><hal><name>android.hardware.health</name>'
                    b'<transport>hwbinder</transport><fqname>@2.1::IHealth/default</fqname>'
                    b'</hal></manifest>'),
                'system/etc/init/hw/init.rc':(0o100644,
                    b'import /init.recovery.${ro.hardware}.rc\n'
                    b'service fastbootd /system/bin/fastbootd\n    disabled\n'
                    b'mount functionfs fastboot /dev/usb-ffs/fastboot\n'
                    b'symlink /config/usb_gadget/g1/functions/ffs.fastboot /config/f1\n'
                    b'start fastbootd\n'),
                'prop.default':(0o100644,b'ro.boot.dynamic_partitions=true\n'),
                'system/etc/recovery.fstab':(0o100644,
                    (ROOT/'recovery/root/system/etc/recovery.fstab').read_bytes())}

    def test_fastboot_runtime_requires_native_daemon_init_and_logical_fstab(self):
        entries = self.entries()
        self.assertFalse(verify_fastboot_runtime(entries)['device_fastbootd_tested'])
        for name in entries:
            changed = copy.copy(entries)
            del changed[name]
            with self.subTest(missing=name),self.assertRaises(ValueError):
                verify_fastboot_runtime(changed)

    def test_rejects_nonexecutable_or_wrong_architecture_fastbootd(self):
        for machine, mode in ((62,0o100755),(183,0o100644)):
            entries = self.entries()
            elf = bytearray(entries['system/bin/fastbootd'][1])
            struct.pack_into('<H',elf,18,machine)
            entries['system/bin/fastbootd'] = (mode,bytes(elf))
            with self.subTest(machine=machine,mode=mode),self.assertRaises(ValueError):
                verify_fastboot_runtime(entries)

    def test_health_startup_requires_reachable_import_and_boot_start(self):
        text = (ROOT/'recovery/root/init.recovery.qcom.rc').read_text()
        self.assertEqual(verify_health_startup(text)['startup_event'], 'boot')
        for old, new in (('import /system/etc/init/android.hardware.health@2.1-service.rc',
                          '# import /system/etc/init/android.hardware.health@2.1-service.rc'),
                         ('start health-hal-2-1', '# start health-hal-2-1'),
                         ('start health-hal-2-1', 'start health-hal-2-0'),
                         ('on boot', 'on property:sys.usb.config=fastboot')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                verify_health_startup(text.replace(old, new))

    def test_health_runtime_rejects_unloaded_or_mismatched_service_and_manifest(self):
        mutations = {
            'system/etc/init/hw/init.rc': (b'import /init.recovery.${ro.hardware}.rc', b'# omitted'),
            'system/etc/init/android.hardware.health@2.1-service.rc':
                (b'service health-hal-2-1', b'service different-health-hal'),
            'vendor/etc/vintf/manifest/android.hardware.health@2.1.xml':
                (b'@2.1::IHealth/default', b'@2.0::IHealth/other'),
        }
        for name, (old, new) in mutations.items():
            entries = self.entries()
            entries[name] = (entries[name][0], entries[name][1].replace(old, new))
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_health_runtime(entries)

    def test_health_runtime_rejects_nonexecutable_and_wrong_architecture_providers(self):
        service = 'system/bin/android.hardware.health@2.1-service'
        entries = self.entries()
        entries[service] = (0o100644, entries[service][1])
        with self.assertRaisesRegex(ValueError, 'executable'):
            verify_health_runtime(entries)
        for name in (service, 'system/lib64/hw/android.hardware.health@2.0-impl-2.1.so'):
            entries = self.entries()
            blob = bytearray(entries[name][1])
            struct.pack_into('<H', blob, 18, 62)
            entries[name] = (entries[name][0], bytes(blob))
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'ARM64'):
                verify_health_runtime(entries)

    def test_static_logical_targets_and_unslotted_recovery_are_rejected(self):
        fstab = (ROOT/'recovery/root/system/etc/recovery.fstab').read_text()
        for changed in (fstab.replace('slotselect,logical','slotselect'),
                        fstab.replace('slotselect,logical','logical'),
                        fstab.replace('system                   /system','/dev/block/bootdevice/by-name/system /system'),
                        '\n'.join(line for line in fstab.splitlines() if '/recovery ' not in line)):
            with self.assertRaises(ValueError):
                verify_fstab(changed)


if __name__ == '__main__':
    unittest.main()
