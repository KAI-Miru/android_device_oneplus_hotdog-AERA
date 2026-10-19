import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from boot_v2 import parse_boot
from verify_image import unpack_newc, verify_native_init, verify_arm64_runtime

def sample_boot():
    image=bytearray(5*4096); image[:8]=b'ANDROID!'
    for offset,value in [(8,16),(16,16),(36,4096),(40,2),(1632,16),(1644,1660),(1648,16)]:
        struct.pack_into('<I',image,offset,value)
    struct.pack_into('<Q',image,1636,3*4096)
    for index in range(1,5): image[index*4096:index*4096+16]=bytes([index])*16
    return image

def archive_entry(name,payload=b'abc',mode=0o100644):
    name=name.encode()+b'\0'
    fields=[1,mode,0,0,1,0,len(payload),0,0,0,0,len(name),0]
    entry=b'070701'+b''.join(f'{n:08x}'.encode() for n in fields)+name
    entry+=b'\0'*((-len(entry))%4); entry+=payload
    return entry+b'\0'*((-len(entry))%4)

class InputTests(unittest.TestCase):
    def native_init_archive(self, target=b'/system/bin/init', script=True, service=True):
        ident = b'\x7fELF\x02\x01\x01' + bytes(9)
        binary = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, 183, 1,
                             0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
        result = archive_entry('init', target, 0o120777)
        result += archive_entry('system/bin/init', binary, 0o100755)
        if script:
            result += archive_entry('system/etc/init/hw/init.rc',
                                    b'import /init.recovery.service.rc\n')
        result += archive_entry('init.recovery.service.rc',
                                b'service recovery /system/bin/recovery\n' if service else b'on boot\n')
        return unpack_newc(result + archive_entry('TRAILER!!!', b''))

    def test_native_aera_init_chain_uses_system_hw_script(self):
        entries = self.native_init_archive()
        self.assertNotIn('init.rc', entries)
        self.assertEqual(verify_native_init(entries), 'system/etc/init/hw/init.rc')

    def test_native_init_rejects_stock_target_and_missing_scripts(self):
        for entries in (self.native_init_archive(target=b'/sbin/stock_init'),
                        self.native_init_archive(script=False),
                        self.native_init_archive(service=False)):
            with self.subTest(entries=list(entries)), self.assertRaises(ValueError):
                verify_native_init(entries)

    def test_native_init_rejects_wrong_architecture_or_nonexecutable(self):
        for machine, mode in ((62, 0o100755), (183, 0o100644)):
            entries = self.native_init_archive()
            binary = bytearray(entries['system/bin/init'][1])
            struct.pack_into('<H', binary, 18, machine)
            entries['system/bin/init'] = (mode, bytes(binary))
            with self.subTest(machine=machine, mode=mode), self.assertRaises(ValueError):
                verify_native_init(entries)

    def test_arm64_only_audit_preserves_gpu_firmware_and_rejects_arm32_libraries(self):
        entries = self.native_init_archive()
        ident = b'\x7fELF\x01\x01\x01' + bytes(9)
        firmware = struct.pack('<16sHHIIIIIHHHHHH', ident, 2, 40, 1,
                               0, 0, 0, 0, 52, 0, 0, 0, 0, 0)
        entries['vendor/firmware/a640_zap.elf'] = (0o100644, firmware)
        report = verify_arm64_runtime(entries)
        self.assertEqual(report['primary'], 'arm64')
        self.assertIsNone(report['secondary'])
        entries['system/lib/libaccidental-arm32.so'] = (0o100644, firmware)
        with self.assertRaisesRegex(ValueError, 'Non-ARM64'):
            verify_arm64_runtime(entries)

    def test_boot_component_boundaries(self):
        _,p=parse_boot(sample_boot())
        self.assertEqual(p['kernel'],bytes([1])*16)
        self.assertEqual(p['dtb.img'],bytes([4])*16)
    def test_rejects_truncated_boot(self):
        with self.assertRaises(ValueError): parse_boot(sample_boot()[:4*4096])
    def test_rejects_unverified_header(self):
        b=sample_boot(); struct.pack_into('<I',b,40,4)
        with self.assertRaises(ValueError): parse_boot(b)
    def test_rejects_overlapping_dtbo(self):
        b=sample_boot(); struct.pack_into('<Q',b,1636,4096)
        with self.assertRaises(ValueError): parse_boot(b)
    def test_cpio_data(self):
        e=unpack_newc(archive_entry('system/bin/recovery')+archive_entry('TRAILER!!!',b''))
        self.assertEqual(e['system/bin/recovery'][1],b'abc')
    def test_cpio_rejects_duplicate_paths(self):
        with self.assertRaises(ValueError): unpack_newc(archive_entry('init')*2+archive_entry('TRAILER!!!',b''))
    def test_cpio_rejects_traversal(self):
        with self.assertRaises(ValueError): unpack_newc(archive_entry('../init')+archive_entry('TRAILER!!!',b''))
    def test_cpio_rejects_truncation(self):
        with self.assertRaises(ValueError): unpack_newc(archive_entry('init')[:-5])

if __name__=='__main__': unittest.main()
