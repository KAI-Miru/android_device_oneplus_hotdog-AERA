import copy
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from verify_hotdog import verify_device_configuration, verify_fastboot_runtime, verify_fstab


class HotdogTests(unittest.TestCase):
    def test_native_device_configuration(self):
        result = verify_device_configuration(ROOT)
        self.assertEqual(result['recovery_partition'],'recovery')

    def entries(self):
        ident = b'\x7fELF\x02\x01\x01'+bytes(9)
        elf = struct.pack('<16sHHIQQQIHHHHHH',ident,2,183,1,0,0,0,0,64,0,0,0,0,0)
        return {'system/bin/fastbootd':(0o100755,elf),
                'system/etc/init/hw/init.rc':(0o100644,
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
