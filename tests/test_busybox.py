"""Keep upstream BusyBox inclusion, identity and required applets verifiable."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_busybox as busybox


def elf(machine=183, kind=1, names=None):
    names = sorted(['[', '[['] + (busybox.SOURCE['required_applets'] if names is None else names))
    ident = b'\x7fELF\x02\x01\x01' + bytes(9)
    header = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, machine, 1,
                         0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    segment = struct.pack('<IIQQQQQQ', kind, 5, 0, 0, 0, 120, 120, 4096)
    return header + segment + b'\0'.join(name.encode() for name in names) + b'\0\0'


class BusyBoxTests(unittest.TestCase):
    def tree(self, directory):
        root = Path(directory)
        for name in ('BoardConfig.mk', 'Android.mk', 'device.mk', 'busybox.mk', 'vendorsetup.sh',
                     'config/busybox-fs-config.fs',
                     'sources.lock.json', 'tools/busybox-source.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        return root

    def test_device_uses_the_exact_upstream_vendor_source(self):
        self.assertEqual(busybox.verify_tree(ROOT), busybox.SOURCE)
        self.assertEqual(busybox.SOURCE['destination'], 'sbin/busybox')
        self.assertFalse((ROOT / 'proprietary/sbin/busybox').exists())
        self.assertNotIn('TW_FORCE_USE_BUSYBOX := true', (ROOT / 'BoardConfig.mk').read_text())

    def test_missing_export_board_setting_or_native_hook_is_rejected(self):
        for filename, old in (
                ('vendorsetup.sh', 'export AERA_USE_BUSYBOX_BINARY=1'),
                ('BoardConfig.mk', 'AERA_USE_BUSYBOX_BINARY := 1'),
                ('Android.mk', 'include $(LOCAL_PATH)/busybox.mk'),
                ('busybox.mk', 'AERA_VENDOR += AERA_USE_BUSYBOX_BINARY="$(AERA_USE_BUSYBOX_BINARY)"'),
                ('busybox.mk', '--ramdisk $(TARGET_RECOVERY_ROOT_OUT)')):
            with self.subTest(file=filename, removed=old), tempfile.TemporaryDirectory() as directory:
                root = self.tree(directory)
                path = root / filename
                path.write_text(path.read_text().replace(old, ''))
                with self.assertRaises(ValueError):
                    busybox.verify_tree(root)

    def test_source_pin_and_identity_cannot_drift_by_updating_manifest(self):
        for filename in ('sources.lock.json', 'tools/busybox-source.json'):
            with self.subTest(file=filename), tempfile.TemporaryDirectory() as directory:
                root = self.tree(directory)
                path = root / filename
                path.write_text(path.read_text().replace(busybox.SOURCE['commit'], '0' * 40))
                with self.assertRaises(ValueError):
                    busybox.verify_tree(root)

    def test_native_packing_cannot_drop_executable_mode_or_add_privileges(self):
        for filename, old, new in (
                ('config/busybox-fs-config.fs', '0755', '0644'),
                ('config/busybox-fs-config.fs', 'caps: 0', 'caps: NET_RAW'),
                ('BoardConfig.mk', 'TARGET_FS_CONFIG_GEN +=', '# TARGET_FS_CONFIG_GEN +='),
                ('device.mk', 'TARGET_RECOVERY_DEVICE_MODULES += fs_config_files_system', ''),
                ('busybox.mk', '--fs-config $(TARGET_OUT_ETC)/fs_config_files', '')):
            with self.subTest(file=filename), tempfile.TemporaryDirectory() as directory:
                root = self.tree(directory)
                path = root / filename
                path.write_text(path.read_text().replace(old, new))
                with self.assertRaises(ValueError):
                    busybox.verify_tree(root)

    def test_actual_generated_permission_table_is_checked_before_packing(self):
        def entry(mode=0o755, uid=0, caps=0, name=b'sbin/busybox'):
            name = name + b'\0'
            name = name.ljust((len(name) + 7) & ~7, b'\0')
            return struct.pack('<HHHHQ', 16 + len(name), mode, uid, 0, caps) + name
        self.assertEqual(busybox.verify_fs_config(entry())['mode'], '0755')
        for blob in (b'', entry(mode=0o644), entry(uid=1000), entry(caps=1),
                     entry()[:-1], entry() + entry(), entry(name=b'sbin/*') + entry()):
            with self.subTest(blob=blob), self.assertRaises(ValueError):
                busybox.verify_fs_config(blob)

    def test_arm64_static_elf_and_real_applet_table_are_required(self):
        self.assertEqual(set(busybox.inspect_blob(elf())), set(['[', '[['] + busybox.SOURCE['required_applets']))
        for blob in (elf(machine=62), elf(kind=2), elf(kind=3), b'not an ELF',
                     elf().replace(b'[\0[[\0', b'help text'), elf() + b'[\0[[\0'):
            with self.subTest(blob=blob[:20]), self.assertRaises(ValueError):
                busybox.inspect_blob(blob)

    def test_each_missing_network_applet_is_rejected(self):
        for missing in busybox.SOURCE['required_applets']:
            names = [name for name in busybox.SOURCE['required_applets'] if name != missing]
            with self.subTest(applet=missing), self.assertRaisesRegex(ValueError, 'required applets missing'):
                busybox.inspect_blob(elf(names=names))

    def test_usage_text_does_not_substitute_for_the_applet_table(self):
        blob = elf(names=['sh']) + b'ip nc nslookup ping timeout udhcpc wget\0'
        with self.assertRaisesRegex(ValueError, 'required applets missing'):
            busybox.inspect_blob(blob)

    def test_unapproved_binary_cannot_pass_packaged_image_audit(self):
        for blob in (b'', elf(), b'\x7fELF' + bytes(100)):
            with self.subTest(size=len(blob)), self.assertRaisesRegex(ValueError, 'pinned upstream prebuilt'):
                busybox.verify_runtime({'sbin/busybox': (0o100755, blob)})
        image_verifier = (ROOT / 'tools/verify_image.py').read_text()
        self.assertIn('busybox_runtime = verify_busybox_runtime(entries)', image_verifier)
        self.assertIn("'busybox_runtime':busybox_runtime", image_verifier)

    def test_missing_nonexecutable_symlink_and_setuid_runtime_are_rejected(self):
        for mode in (0, 0o100644, 0o120777, 0o104755):
            with self.subTest(mode=oct(mode)), self.assertRaisesRegex(ValueError, 'regular executable'):
                busybox.verify_runtime({'sbin/busybox': (mode, elf())})

    def test_staging_rejects_an_unapproved_upstream_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'busybox'
            source.write_bytes(elf())
            with self.assertRaisesRegex(ValueError, 'pinned upstream prebuilt'):
                busybox.verify_staging(source, root / 'ramdisk')

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('make'), 'GNU Make integration')
    def test_native_hook_keeps_resolved_flag_after_cached_environment_and_checks_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            makefile = root / 'Makefile'
            makefile.write_text(f'''LOCAL_PATH := {ROOT.as_posix()}
TARGET_ARCH := arm64
TARGET_RECOVERY_ROOT_OUT := {root.as_posix()}/ramdisk
TARGET_OUT_ETC := {root.as_posix()}/system/etc
AERA_USE_BUSYBOX_BINARY := 1
AERA_VENDOR := upstream-hook AERA_USE_BUSYBOX_BINARY=0
include {ROOT.as_posix()}/busybox.mk
LOCAL_PATH := wrong/later/module
.PHONY: show check
show:
\t@printf '%s\\n' '$(AERA_VENDOR)' '$(BOARD_RECOVERY_IMAGE_PREPARE)'
check:
\t@$(BOARD_RECOVERY_IMAGE_PREPARE)
''')
            shown = subprocess.run(['make', '-s', 'show'], cwd=root, capture_output=True, text=True, check=True)
            lines = shown.stdout.splitlines()
            self.assertTrue(lines[0].endswith('AERA_USE_BUSYBOX_BINARY="1"'))
            self.assertIn(str(ROOT / 'tools/verify_busybox.py'), lines[1])
            self.assertNotIn('wrong/later/module', lines[1])
            self.assertTrue(lines[1].startswith('/usr/bin/python3 '))
            # A later module's LOCAL_PATH and a poisoned PATH must not select
            # Android's hermetic Python or a stale native staging directory.
            poison = root / 'poison'
            poison.mkdir()
            (poison / 'python3').write_text('#!/bin/sh\nexit 97\n')
            (poison / 'python3').chmod(0o755)
            checked = subprocess.run(['make', '-s', 'check'], cwd=root, capture_output=True, text=True,
                                     env=dict(os.environ, PATH=str(poison) + ':' + os.environ['PATH']))
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn('source must be a regular file', checked.stderr)
            disabled = makefile.read_text().replace('AERA_USE_BUSYBOX_BINARY := 1', 'AERA_USE_BUSYBOX_BINARY := 0')
            makefile.write_text(disabled)
            rejected = subprocess.run(['make', '-s', 'show'], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('requires AERA_USE_BUSYBOX_BINARY=1', rejected.stderr)


if __name__ == '__main__':
    unittest.main()
