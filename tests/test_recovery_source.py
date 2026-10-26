import json
import hashlib
import struct
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_recovery_source import verify, verify_keystore_source
from verify_keystore import verify_keystore_runtime


class RecoverySourceTests(unittest.TestCase):
    def test_pinned_clean_source_is_required_without_rewriting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'source/bootable/recovery'
            checkout.mkdir(parents=True)
            source = checkout / 'test.cpp'
            source.write_text('original source\n')
            git = ['git', '-C', str(checkout)]
            for args in (['init', '-q'], ['config', 'user.name', 'Test'],
                         ['config', 'user.email', 'test@example.invalid'],
                         ['add', '.'], ['commit', '-qm', 'Source fixture']):
                subprocess.run(git + args, check=True, capture_output=True)
            revision = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
            device = root / 'device'
            device.mkdir()
            project = {'path': 'bootable/recovery', 'url': 'https://example.invalid/fork.git',
                       'branch': 'miru', 'commit': revision}
            lock = device / 'sources.lock.json'
            lock.write_text(json.dumps({'projects': [project]}))
            report = verify(root / 'source', root / 'reports', device)
            self.assertFalse(report['build_time_source_patches'])
            self.assertEqual(source.read_text(), 'original source\n')
            source.write_text('changed source\n')
            with self.assertRaisesRegex(ValueError, 'uncommitted'):
                verify(root / 'source', root / 'reports', device)
            self.assertEqual(source.read_text(), 'changed source\n')
            project['commit'] = '0' * 40
            lock.write_text(json.dumps({'projects': [project]}))
            with self.assertRaisesRegex(ValueError, 'requires'):
                verify(root / 'source', root / 'reports', device)


class KeystoreSourceTests(unittest.TestCase):
    def fixture(self, root):
        checkout = root / 'bootable/recovery'
        init = checkout / 'etc/init/keystore2.rc'
        init.parent.mkdir(parents=True)
        init.write_bytes(b'on late-init\n    start keystore2\nservice keystore2 /system/bin/keystore2 /tmp/misc/keystore --recovery\n')
        security = root / 'system/security'
        files = {'keystore2/src/keystore2_main.rs': b'reviewed entrypoint\n',
                 'keystore2/src/globals.rs': b'reviewed GC gate\n',
                 'keystore2/Android.bp': b'reviewed dependencies\n'}
        for name, content in files.items():
            path = security / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        git = ['git', '-C', str(security)]
        for args in (['init', '-q'], ['config', 'user.name', 'Test'],
                     ['config', 'user.email', 'test@example.invalid'], ['add', '.'],
                     ['-c', 'commit.gpgsign=false', 'commit', '-qm', 'Keystore fixture']):
            subprocess.run(git + args, check=True, capture_output=True)
        project = {'path': 'system/security', 'url': 'https://example.invalid/security.git',
                   'branch': 'miru', 'commit': subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()}
        origin = {key: project[key] for key in ('url', 'branch', 'commit')}
        origin['files'] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
        device = root / 'device'
        metadata = device / 'tools/keystore-source.json'
        metadata.parent.mkdir(parents=True)
        metadata.write_text(json.dumps(origin))
        return checkout, security, device, metadata, {'projects': [project]}, origin

    def test_exact_clean_platform_source_and_gc_gate_are_required(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout, security, device, metadata, lock, origin = self.fixture(root)
            result = verify_keystore_source(root, lock, checkout, device)
            self.assertTrue(result['boot_completed_gc_gate_preserved'])
            for field, value in (('url', 'https://example.invalid/other.git'),
                                 ('branch', 'other'), ('commit', '0' * 40)):
                old = lock['projects'][0][field]
                lock['projects'][0][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'requires review'):
                    verify_keystore_source(root, lock, checkout, device)
                lock['projects'][0][field] = old
            with self.assertRaisesRegex(ValueError, 'requires review'):
                verify_keystore_source(root, {'projects': []}, checkout, device)
            origin['files']['keystore2/src/globals.rs'] = '0' * 64
            metadata.write_text(json.dumps(origin))
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                verify_keystore_source(root, lock, checkout, device)
            metadata.unlink()
            with self.assertRaises(FileNotFoundError):
                verify_keystore_source(root, lock, checkout, device)

    def test_wrong_revision_dirty_source_and_copied_entrypoint_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout, security, device, metadata, lock, origin = self.fixture(root)
            commit = origin['commit']
            lock['projects'][0]['commit'] = origin['commit'] = '0' * 40
            metadata.write_text(json.dumps(origin))
            with self.assertRaisesRegex(ValueError, 'exact pinned revision'):
                verify_keystore_source(root, lock, checkout, device)
            lock['projects'][0]['commit'] = origin['commit'] = commit
            metadata.write_text(json.dumps(origin))
            source = security / 'keystore2/src/globals.rs'
            original = source.read_bytes()
            source.write_bytes(original + b'changed GC gate\n')
            with self.assertRaisesRegex(ValueError, 'uncommitted'):
                verify_keystore_source(root, lock, checkout, device)
            source.write_bytes(original)
            (checkout / 'aera_keystore').mkdir()
            with self.assertRaisesRegex(ValueError, 'copied entrypoint'):
                verify_keystore_source(root, lock, checkout, device)

    def test_keystore_runtime_rejects_wrong_options_startup_and_architecture(self):
        ident = b'\x7fELF\x02\x01\x01' + bytes(9)
        elf = struct.pack('<16sHHIQQQIHHHHHH', ident, 2, 183, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
        name, init = 'system/bin/keystore2', 'system/etc/init/keystore2.rc'
        config = b'on late-init\n    start keystore2\nservice keystore2 /system/bin/keystore2 /tmp/misc/keystore --recovery\n'
        entries = {name: (0o100755, elf), init: (0o100644, config)}
        self.assertEqual(verify_keystore_runtime(entries)['recovery_argument'], '--recovery')
        for old, new in ((b' --recovery', b''), (b' --recovery', b' --recovery-extra'),
                         (b'/bin/keystore2 ', b'/bin/aera_keystore2 '),
                         (b'/tmp/misc/keystore', b'/data/misc/keystore'),
                         (b'on late-init', b'on property:test.ready=1'),
                         (b'    start keystore2', b'    # start keystore2')):
            entries[init] = (0o100644, config.replace(old, new))
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                verify_keystore_runtime(entries)
        for addition in (b'    setprop sys.boot_completed 1\n',
                         b'service keystore2 /system/bin/keystore2 /tmp/misc/keystore --recovery\n'):
            entries[init] = (0o100644, config + addition)
            with self.assertRaises(ValueError):
                verify_keystore_runtime(entries)
        entries[init] = (0o100644, config)
        for invalid in ((0o100644, elf), (0o120777, elf),
                        (0o100755, elf[:18] + struct.pack('<H', 62) + elf[20:])):
            entries[name] = invalid
            with self.assertRaises(ValueError):
                verify_keystore_runtime(entries)
        del entries[name]
        with self.assertRaisesRegex(ValueError, 'Missing'):
            verify_keystore_runtime(entries)
