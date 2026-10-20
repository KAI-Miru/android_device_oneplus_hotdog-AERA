import copy
import shutil
from pathlib import Path
import struct
import sys
import unittest
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_hotdog import verify_device_configuration, verify_fastboot_runtime, verify_fstab, verify_health_runtime, verify_health_startup, verify_fastboot_hal_manifest, verify_fastboot_hal_runtime, FASTBOOT_HAL_MANIFEST, FASTBOOT_HAL_PROVIDER


FASTBOOT_DECLARATION = b'''<manifest version="2.0" type="device">
    <hal format="hidl"><name>android.hardware.fastboot</name>
        <transport arch="64">passthrough</transport>
        <fqname>@1.1::IFastboot/default</fqname>
    </hal>
</manifest>'''


def passthrough_provider(symbol='HIDL_FETCH_IFastboot', machine=183, binding=1, visibility=0, defined=True):
    """Small ELF fixture with a real dynamic symbol table; never executed."""
    names = b'\0.shstrtab\0.dynstr\0.dynsym\0.text\0'
    strings = b'\0' + symbol.encode() + b'\0'
    symbols = bytes(24) + struct.pack('<IBBHQQ', 1, binding << 4 | 2, visibility, 4 if defined else 0, 0, 4)
    blobs = (names, strings, symbols, struct.pack('<I', 0xd65f03c0))
    data = bytearray(64)
    offsets = []
    for blob in blobs:
        data.extend(bytes((-len(data)) % 8))
        offsets.append(len(data))
        data.extend(blob)
    data.extend(bytes((-len(data)) % 8))
    section_offset = len(data)
    data.extend(bytes(64))
    for index, (name, kind) in enumerate(((b'.shstrtab', 3), (b'.dynstr', 3),
                                         (b'.dynsym', 11), (b'.text', 1))):
        data.extend(struct.pack('<IIQQQQIIQQ', names.index(name), kind, 6 if kind == 1 else 0,
                                0, offsets[index], len(blobs[index]), 2 if kind == 11 else 0,
                                1 if kind == 11 else 0, 8, 24 if kind == 11 else 0))
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    data[:64] = struct.pack('<16sHHIQQQIHHHHHH', ident, 3, machine, 1, 0, 0,
                            section_offset, 0, 64, 0, 0, 64, 5, 1)
    return bytes(data)


class HotdogTests(unittest.TestCase):
    def test_native_device_configuration(self):
        result = verify_device_configuration(ROOT)
        self.assertEqual(result['recovery_partition'],'recovery')

    def entries(self):
        ident = b'\x7fELF\x02\x01\x01'+bytes(9)
        elf = struct.pack('<16sHHIQQQIHHHHHH',ident,2,183,1,0,0,0,0,64,0,0,0,0,0)
        return {'system/bin/fastbootd':(0o100755,elf),
                FASTBOOT_HAL_MANIFEST:(0o100644,FASTBOOT_DECLARATION),
                FASTBOOT_HAL_PROVIDER:(0o100644,passthrough_provider()),
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

    def test_device_manifest_declares_the_bundled_passthrough_fastboot_hal(self):
        declaration = verify_fastboot_hal_manifest((ROOT/'manifest.xml').read_bytes())
        self.assertEqual(declaration['interface'], '@1.1::IFastboot/default')

    def test_fastboot_hal_declaration_requires_device_hidl_default_and_matching_transport(self):
        for old, new in ((b'type="device"', b'type="framework"'),
                         (b'format="hidl"', b'format="aidl"'),
                         (b'passthrough', b'hwbinder'), (b'arch="64"', b'arch="32"'),
                         (b'arch="64"', b''), (b'@1.1', b'@1.0'),
                         (b'IFastboot/default', b'IFastboot/other'),
                         (b'android.hardware.fastboot', b'android.hardware.other')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                verify_fastboot_hal_manifest(FASTBOOT_DECLARATION.replace(old, new))
        hal = FASTBOOT_DECLARATION.split(b'<hal', 1)[1].split(b'</hal>', 1)[0]
        duplicate = FASTBOOT_DECLARATION.replace(b'</manifest>', b'<hal' + hal + b'</hal></manifest>')
        with self.assertRaises(ValueError):
            verify_fastboot_hal_manifest(duplicate)

    def test_fastboot_provider_requires_a_real_arm64_exported_factory(self):
        self.assertEqual(verify_fastboot_hal_runtime(self.entries())['provider'], FASTBOOT_HAL_PROVIDER)
        for kwargs in ({'machine': 62}, {'symbol': 'DifferentFactory'}, {'defined': False},
                       {'binding': 0}, {'visibility': 2}):
            entries = self.entries()
            entries[FASTBOOT_HAL_PROVIDER] = (0o100644,passthrough_provider(**kwargs))
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                verify_fastboot_hal_runtime(entries)
        for path in (FASTBOOT_HAL_MANIFEST, FASTBOOT_HAL_PROVIDER):
            entries = self.entries()
            entries[path] = (0o120777, entries[path][1])
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify_fastboot_hal_runtime(entries)

    def test_fastboot_declaration_must_be_staged_at_the_device_manifest_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT/'recovery', root/'recovery')
            for path in ('manifest.xml', 'device.mk', 'BoardConfig.mk', 'config/device.json'):
                destination = root/path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/path, destination)
            product = root/'device.mk'
            text = product.read_text().replace(
                '$(LOCAL_PATH)/manifest.xml:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/etc/vintf/manifest.xml',
                '$(LOCAL_PATH)/manifest.xml:$(TARGET_COPY_OUT_RECOVERY)/root/vendor/etc/wrong.xml')
            product.write_text(text)
            with self.assertRaisesRegex(ValueError, 'manifest must be copied'):
                verify_device_configuration(root)


if __name__ == '__main__':
    unittest.main()
