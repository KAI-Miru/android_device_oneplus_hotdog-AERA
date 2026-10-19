import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from verify_recovery_source import verify


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
