import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from import_vendor import official_crypto_root, select_library
from verify_image import verify_crypto_service_configuration, verify_gatekeeper_spu_configuration


class OfficialCryptoTests(unittest.TestCase):
    def services(self):
        text = ''
        for name, exe in (('qseecomd', 'qseecomd'),
                          ('keymaster-4-0-qti', 'android.hardware.keymaster@4.0-service-qti'),
                          ('gatekeeper-1-0-qti', 'android.hardware.gatekeeper@1.0-service-qti')):
            text += (f'service {name} /system/bin/{exe}\n'
                     '    override\n    user root\n    group root\n    disabled\n'
                     '    seclabel u:r:recovery:s0\n'
                     '    setenv LD_LIBRARY_PATH /system/lib64:/vendor/lib64:/system/lib:/vendor/lib:/sbin\n\n')
        return {
            'init.recovery.hotdog-crypto.rc': (0o100644, text.encode()),
            'init.recovery.qcom.rc': (0o100644,
                b'import /init.recovery.qcom_decrypt.rc\nimport /init.recovery.hotdog-crypto.rc\n'
                b'on init\n    setprop vendor.gatekeeper.disable_spu true\n'
                b'on property:crypto.ready=0 && property:twrp.user.0.decrypt=1\n'
                b'    start qseecomd\n    start gatekeeper-1-0-qti\n'),
        }

    def test_persist_is_writable_before_crypto_startup(self):
        root = Path(__file__).resolve().parents[1]
        lines = (root / 'recovery/root/init.recovery.qcom.rc').read_text().splitlines()
        action = None
        mounts = []
        for line in lines:
            if line and not line[0].isspace() and not line.startswith('#'):
                action = line
            fields = line.split()
            if fields[:1] == ['mount'] and '/mnt/vendor/persist' in fields:
                mounts.append((action, fields))
        self.assertEqual(mounts, [('on fs', ['mount', 'ext4',
            '/dev/block/bootdevice/by-name/persist', '/mnt/vendor/persist', 'rw'])])

    def test_standard_services_keep_official_providers_when_vendor_is_mounted(self):
        self.assertEqual(len(verify_crypto_service_configuration(self.services())), 3)

    def test_gatekeeper_rejects_missing_or_enabled_spu_configuration(self):
        for value in (b'', b'    setprop vendor.gatekeeper.disable_spu false\n'):
            entries = self.services()
            name = 'init.recovery.qcom.rc'
            entries[name] = (0o100644, entries[name][1].replace(
                b'    setprop vendor.gatekeeper.disable_spu true\n', value))
            with self.assertRaisesRegex(ValueError, 'SPU on init'):
                verify_crypto_service_configuration(entries)

    def test_gatekeeper_setting_must_precede_crypto_startup(self):
        entries = self.services()
        name = 'init.recovery.qcom.rc'
        entries[name] = (0o100644, entries[name][1].replace(b'on init\n', b'on boot\n'))
        with self.assertRaisesRegex(ValueError, 'SPU on init'):
            verify_gatekeeper_spu_configuration(entries)
        report = verify_gatekeeper_spu_configuration(self.services())
        self.assertTrue(report['disable_spu'])
        self.assertFalse(report['credential_unlock_tested'])

    def test_screen_verifier_requires_owner_unlock_and_completed_crypto_cleanup(self):
        name = 'init.recovery.qcom.rc'
        for old, new in (
            (b' && property:twrp.user.0.decrypt=1', b''),
            (b'property:crypto.ready=0', b'property:crypto.ready=1'),
            (b'    start gatekeeper-1-0-qti\n', b''),
            (b'    start qseecomd\n', b''),
            (b'    start gatekeeper-1-0-qti\n', b'    start gatekeeper-1-0-qti\n    start keymaster-4-0-qti\n'),
        ):
            entries = self.services()
            entries[name] = (0o100644, entries[name][1].replace(old, new))
            with self.subTest(change=old), self.assertRaisesRegex(ValueError, 'Screen verifier'):
                verify_gatekeeper_spu_configuration(entries)
        report = verify_gatekeeper_spu_configuration(self.services())
        self.assertTrue(report['post_decrypt_verifier'])

    def test_vendor_shadowing_and_wrong_import_order_are_rejected(self):
        entries = self.services()
        name = 'init.recovery.hotdog-crypto.rc'
        entries[name] = (0o100644, entries[name][1].replace(
            b'/system/lib64:/vendor/lib64', b'/vendor/lib64:/system/lib64'))
        with self.assertRaisesRegex(ValueError, 'shadowed'):
            verify_crypto_service_configuration(entries)
        entries = self.services()
        entries['init.recovery.qcom.rc'] = (0o100644,
            b'import /init.recovery.hotdog-crypto.rc\nimport /init.recovery.qcom_decrypt.rc\n')
        with self.assertRaisesRegex(ValueError, 'imported before'):
            verify_crypto_service_configuration(entries)

    def test_blob_import_requires_the_pinned_official_revision(self):
        source = {'commit': '1' * 40}
        with patch('import_vendor.subprocess.check_output', return_value='2' * 40 + '\n'):
            with self.assertRaisesRegex(ValueError, 'Official crypto checkout must be'):
                official_crypto_root(Path('/tmp/official-test'), source)

    def test_library_selection_ignores_extracted_symlink_placeholders(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = root / 'placeholder', root / 'real'
            first.mkdir(); second.mkdir()
            (first / 'provider.so').write_bytes(b'../real/provider.so')
            (second / 'provider.so').write_bytes(b'\x7fELF' + bytes(64))
            self.assertEqual(select_library('provider.so', [first, second]), second / 'provider.so')
            with self.assertRaises(FileNotFoundError):
                select_library('missing.so', [first, second])


if __name__ == '__main__':
    unittest.main()
