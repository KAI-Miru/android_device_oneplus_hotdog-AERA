from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from environment_fingerprint import INPUTS, fingerprint
from verify_prepared_environment import verify
import json
import shutil


class EnvironmentTests(unittest.TestCase):
    def test_plan_hash_is_portable_and_rejects_changed_source_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            roots = [Path(directory) / name for name in ('first', 'second')]
            for root in roots:
                for name in INPUTS:
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(name)
            self.assertEqual(fingerprint(roots[0]), fingerprint(roots[1]))
            (roots[1] / 'sources.lock.json').write_text('Changed upstream revision')
            self.assertNotEqual(fingerprint(roots[0]), fingerprint(roots[1]))

    def test_known_reader_repair_preserves_all_source_and_host_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current = base / 'current'
            retained = base / 'aera/device/oneplus/hotdog'
            for name in INPUTS:
                path = retained / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(name)
            old = fingerprint(retained)
            (base / 'aera/.aera-prepared-environment.json').write_text(json.dumps({'fingerprint': old}))
            shutil.copytree(retained, current)
            (current / 'tools/prepared_snapshot.py').write_text('reader skips transient FIFO')
            (current / 'ci/use-prepared.sh').write_text('verify compatible reader inputs')
            report = verify(current, base / 'aera', base / 'reports', legacy={old})
            self.assertEqual(set(report['compatible_reader_repair']),
                             {'tools/prepared_snapshot.py', 'ci/use-prepared.sh'})
            for name in ('sources.lock.json', 'ci/compile.sh', 'ci/Builder.Dockerfile'):
                original = (current / name).read_bytes()
                (current / name).write_text('changed host inputs')
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'inputs changed'):
                    verify(current, base / 'aera', base / 'reports', legacy={old})
                (current / name).write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'Unknown or altered'):
                verify(current, base / 'aera', base / 'reports', legacy=set())
            (retained / 'ci/compile.sh').write_text('tampered retained identity')
            with self.assertRaisesRegex(ValueError, 'Unknown or altered'):
                verify(current, base / 'aera', base / 'reports', legacy={old})
