from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ci'))
from assemble_inputs import assemble

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.device, self.runner = self.root / 'device', self.root / 'runner'
        for checkout in (self.device, self.runner):
            checkout.mkdir()
            subprocess.run(['git', '-C', str(checkout), 'init', '-q'], check=True)
            subprocess.run(['git', '-C', str(checkout), 'config', 'user.name', 'Test'], check=True)
            subprocess.run(['git', '-C', str(checkout), 'config', 'user.email', 'test@example.invalid'], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, root, name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def commit(self, root):
        subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'fixture'], check=True)
        return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()

    def test_selected_device_and_runner_revisions_are_kept_separate(self):
        self.write(self.device, 'BoardConfig.mk', 'ARM64 and secondary ARM')
        self.write(self.device, 'tools/verify_tree.py', 'device verifier')
        self.write(self.device, 'tools/verify_recovery_source.py', 'clean fork verifier')
        self.write(self.runner, 'ci/build.sh', 'trusted build script')
        self.write(self.runner, 'tools/select_recovery_source.py', 'select pinned fork')
        self.write(self.runner, 'tools/environment_fingerprint.py', 'host fingerprint')
        device_revision, runner_revision = self.commit(self.device), self.commit(self.runner)
        self.write(self.device, 'untracked-device.log', 'must stay outside build inputs')
        output = self.root / 'inputs'
        report = assemble(self.device, self.runner, output)
        self.assertEqual(report['device_revision'], device_revision)
        self.assertEqual(report['runner_revision'], runner_revision)
        self.assertEqual((output / 'BoardConfig.mk').read_text(), 'ARM64 and secondary ARM')
        self.assertEqual((output / 'ci/build.sh').read_text(), 'trusted build script')
        self.assertEqual((output / 'tools/select_recovery_source.py').read_text(), 'select pinned fork')
        self.assertTrue((output / 'tools/verify_recovery_source.py').is_file())
        self.assertFalse((output / '.git').exists())
        self.assertFalse((output / 'untracked-device.log').exists())

    def test_legacy_device_runner_files_do_not_override_trusted_runner(self):
        self.write(self.device, 'ci/build.sh', 'old device copy')
        self.write(self.device, 'ci/bootloader-layout.json', 'device layout')
        self.write(self.device, 'BoardConfig.mk', 'device')
        self.write(self.runner, 'ci/build.sh', 'runner copy')
        self.commit(self.device)
        self.commit(self.runner)
        output = self.root / 'inputs'
        assemble(self.device, self.runner, output)
        self.assertEqual((output / 'ci/build.sh').read_text(), 'runner copy')
        self.assertEqual((output / 'ci/bootloader-layout.json').read_text(), 'device layout')

    def test_nonempty_or_nested_outputs_are_rejected(self):
        self.write(self.device, 'BoardConfig.mk', 'device')
        self.write(self.runner, 'ci/build.sh', 'runner')
        self.commit(self.device)
        self.commit(self.runner)
        for output in (self.device / 'build', self.runner / 'build'):
            with self.assertRaisesRegex(ValueError, 'outside'):
                assemble(self.device, self.runner, output)
        output = self.root / 'existing'
        output.mkdir()
        marker = output / 'keep'
        marker.write_text('existing work')
        with self.assertRaisesRegex(ValueError, 'empty'):
            assemble(self.device, self.runner, output)
        self.assertEqual(marker.read_text(), 'existing work')

if __name__ == '__main__': unittest.main()
