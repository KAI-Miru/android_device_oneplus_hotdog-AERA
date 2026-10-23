"""Require review if the upstream checkpoint query or mount path changes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_recovery_source import verify_checkpoint_source


class CheckpointSourceTests(unittest.TestCase):
    def fixture(self, root):
        checkout = root / 'bootable/recovery'
        metadata = checkout / 'aera_checkpoint/source.json'
        metadata.parent.mkdir(parents=True)
        source = root / 'system/vold/MetadataCrypt.cpp'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'reviewed source\r\n')
        project = {'path': 'system/vold', 'url': 'https://example.invalid/vold.git',
                   'commit': 'a' * 40}
        origin = {'symbol': '_ZN7android4vold18cp_needsCheckpointEv',
                  'projects': [dict(project, files={'MetadataCrypt.cpp':
                      hashlib.sha256(b'reviewed source\n').hexdigest()})]}
        metadata.write_text(json.dumps(origin))
        return checkout, metadata, source, {'projects': [project]}, origin

    def test_exact_source_and_pin_accept_crlf_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout, _, source, lock, _ = self.fixture(root)
            before = source.read_bytes()
            result = verify_checkpoint_source(root, lock, checkout)
            self.assertTrue(result['platform_sources_unchanged'])
            self.assertTrue(result['pending_transactions_preserved'])
            self.assertEqual(source.read_bytes(), before)

    def test_changed_missing_or_retargeted_platform_sources_require_review(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout, _, source, lock, _ = self.fixture(root)
            for field, value in (('commit', 'b' * 40), ('url', 'https://example.invalid/other.git')):
                old = lock['projects'][0][field]
                lock['projects'][0][field] = value
                with self.assertRaisesRegex(ValueError, 'requires review'):
                    verify_checkpoint_source(root, lock, checkout)
                lock['projects'][0][field] = old
            source.write_text('changed source\n')
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                verify_checkpoint_source(root, lock, checkout)
            source.unlink()
            with self.assertRaisesRegex(ValueError, 'identity differs'):
                verify_checkpoint_source(root, lock, checkout)

    def test_wrong_symbol_and_unsafe_relative_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkout, metadata, _, lock, origin = self.fixture(root)
            symbol = origin['symbol']
            origin['symbol'] = 'some_other_function'
            metadata.write_text(json.dumps(origin))
            with self.assertRaisesRegex(ValueError, 'query symbol'):
                verify_checkpoint_source(root, lock, checkout)
            origin['symbol'] = symbol
            origin['projects'][0]['files'] = {'../MetadataCrypt.cpp': '0' * 64}
            metadata.write_text(json.dumps(origin))
            with self.assertRaisesRegex(ValueError, 'source path'):
                verify_checkpoint_source(root, lock, checkout)

    def test_old_recovery_without_wrapper_has_no_new_dependency(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(verify_checkpoint_source(folder, {'projects': []}, folder))


if __name__ == '__main__':
    unittest.main()
