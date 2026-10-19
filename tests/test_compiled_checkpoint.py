import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from environment_fingerprint import INPUTS, fingerprint
from verify_prepared_environment import verify
from retained_image import select
from prepared_snapshot import pack, restore
from select_recovery_source import select as select_source


class CompiledCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.retained = self.source / 'device/oneplus/hotdog'
        self.current = self.root / 'current'
        for name in INPUTS:
            target = self.retained / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(name)
        self.plan = {'manifest_commit': 'a' * 40, 'projects': [
            {'path': 'bootable/recovery', 'name': 'android_bootable_recovery',
             'url': 'https://github.com/AERA-Recovery/android_bootable_recovery.git',
             'remote': 'AERA', 'branch': 'aera-16.0', 'commit': 'b' * 40},
            {'path': 'bionic', 'commit': 'c' * 40}]}
        (self.retained / 'sources.lock.json').write_text(json.dumps(self.plan))
        self.old = fingerprint(self.retained)
        (self.source / '.aera-prepared-environment.json').write_text(json.dumps({'fingerprint': self.old}))
        shutil.copytree(self.retained, self.current)
        self.plan['projects'][0].update(url='https://github.com/KAI-Miru/android_bootable_recovery.git',
                                        remote='Miru', branch='miru', commit='d' * 40)
        self.write_plan()
        (self.current / 'tools/prepare_manifest.py').write_text('Add the pinned fork remote')

    def tearDown(self):
        self.temp.cleanup()

    def write_plan(self):
        (self.current / 'sources.lock.json').write_text(json.dumps(self.plan))

    def check(self, legacy=True):
        return verify(self.current, self.source, self.root / 'reports',
                      legacy={self.old} if legacy else set())

    def test_recovery_only_update_keeps_other_sources_and_host_inputs_fixed(self):
        report = self.check()
        self.assertEqual(report['recovery_source_update']['to'], 'd' * 40)
        self.assertTrue(report['non_recovery_sources_toolchains_host_inputs_match'])
        self.assertIsNone(report['compiled_checkpoint'])
        self.plan['projects'][1]['commit'] = 'e' * 40
        self.write_plan()
        with self.assertRaisesRegex(ValueError, 'Non-recovery'):
            self.check()

    def test_host_changes_and_unreviewed_forks_are_rejected(self):
        path = self.current / 'ci/compile.sh'
        original = path.read_text()
        path.write_text('different compile flags')
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.check()
        path.write_text(original)
        self.plan['projects'][0]['url'] = 'https://example.invalid/other.git'
        self.write_plan()
        with self.assertRaisesRegex(ValueError, 'reviewed miru fork'):
            self.check()

    def test_source_cache_uses_the_fork_remote_for_later_object_fetches(self):
        checkout = self.source / 'bootable/recovery'
        checkout.mkdir(parents=True)
        code = checkout / 'recovery.cpp'
        code.write_text('committed source\n')
        git = ['git', '-C', str(checkout)]
        for args in (['init', '-q'], ['config', 'user.name', 'Test'],
                     ['config', 'user.email', 'test@example.invalid'],
                     ['add', '.'], ['commit', '-qm', 'Source fixture'],
                     ['remote', 'add', 'AERA', 'https://github.com/AERA-Recovery/android_bootable_recovery.git']):
            subprocess.run(git + args, check=True, capture_output=True)
        self.plan['projects'][0]['commit'] = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
        self.write_plan()
        select_source(self.current, self.source)
        url = subprocess.check_output(git + ['remote', 'get-url', 'AERA'], text=True).strip()
        self.assertEqual(url, self.plan['projects'][0]['url'])
        self.assertEqual(code.read_text(), 'committed source\n')
        self.assertFalse(subprocess.check_output(git + ['status', '--porcelain']))

    def test_compiled_cache_requires_its_image_and_ninja_state(self):
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            self.check(legacy=False)
        image = self.source / 'out/target/product/hotdog/recovery.img'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'verified image fixture')
        (self.source / 'out/.ninja_log').write_text('ninja state')
        marker = self.source / '.aera-compiled-checkpoint.json'
        marker.write_text(json.dumps({'schema': 1, 'kind': 'compiled', 'arm64_object_count': 1,
                                     'ninja_state_retained': True,
                                     'image_sha256': hashlib.sha256(image.read_bytes()).hexdigest()}))
        self.assertIsNotNone(self.check(legacy=False)['compiled_checkpoint'])
        image.write_bytes(b'altered image fixture')
        with self.assertRaisesRegex(ValueError, 'Invalid compiled checkpoint'):
            self.check(legacy=False)

    def test_runtime_export_excludes_inputs_and_rejects_credentials(self):
        def archive(names):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as output:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = 4
                    output.addfile(member, io.BytesIO(b'data'))
            return stream.getvalue()
        script = ROOT / 'ci/export_checkpoint_runtime.py'
        target = self.root / 'runtime.tar'
        subprocess.run([sys.executable, str(script), str(target)],
                       input=archive(['usr/bin/bash', 'device-tree/private-input',
                                      'aera/out/object', 'builder-archive/part00', 'checkpoint/part00']), check=True)
        with tarfile.open(target) as result:
            self.assertEqual(result.getnames(), ['usr/bin/bash'])
        denied = subprocess.run([sys.executable, str(script), str(self.root / 'denied.tar')],
                                input=archive(['root/.docker/config.json']), capture_output=True)
        self.assertNotEqual(denied.returncode, 0)

    def test_retained_image_requires_exact_hash_before_copying(self):
        original = self.source / 'device/oneplus/hotdog/prebuilt/kernel'
        original.parent.mkdir(parents=True)
        original.write_bytes(b'caller-approved image fixture')
        with self.assertRaisesRegex(ValueError, 'absent'):
            select(self.source, '0' * 64)
        self.assertFalse((self.source / '.external-inputs/Image').exists())
        expected = hashlib.sha256(original.read_bytes()).hexdigest()
        selected = select(self.source, expected)
        self.assertEqual(selected.read_bytes(), original.read_bytes())
        original.unlink()
        self.assertEqual(select(self.source, expected), selected)

    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('ninja') and
                         shutil.which('g++'), 'Requires native Ninja and a C++ compiler')
    def test_restored_objects_rebuild_only_the_changed_file_and_dependents(self):
        source = self.root / 'compiled'
        source.mkdir()
        (source / 'a.cpp').write_text('int first() { return 1; }\n')
        (source / 'b.cpp').write_text('int second() { return 2; }\n')
        (source / 'build.ninja').write_text(
            'rule compile\n  command = g++ -c $in -o $out\n'
            'rule archive\n  command = ar rcs $out $in\n'
            'build a.o: compile a.cpp\nbuild b.o: compile b.cpp\n'
            'build recovery.a: archive a.o b.o\ndefault recovery.a\n')
        subprocess.run(['ninja', '-C', str(source)], check=True, capture_output=True)
        b_timestamp = (source / 'b.o').stat().st_mtime_ns
        snapshot = self.root / 'compiled-snapshot'
        pack(source, snapshot, remove_source=True)
        self.assertFalse(source.exists())
        destination = self.root / 'restored'
        destination.mkdir()
        restore(snapshot, destination)
        target = destination / 'aera'
        unchanged = subprocess.check_output(['ninja', '-C', str(target)], text=True)
        self.assertIn('no work to do', unchanged)
        time.sleep(0.02)
        (target / 'a.cpp').write_text('int first() { return 3; }\n')
        changed = subprocess.check_output(['ninja', '-C', str(target)], text=True)
        self.assertIn('g++ -c a.cpp', changed)
        self.assertIn('ar rcs recovery.a', changed)
        self.assertNotIn('g++ -c b.cpp', changed)
        self.assertEqual((target / 'b.o').stat().st_mtime_ns, b_timestamp)


if __name__ == '__main__':
    unittest.main()
