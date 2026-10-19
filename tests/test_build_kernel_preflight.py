import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash'),
                     'Requires native Linux shell execution')
class BuildKernelPreflightTests(unittest.TestCase):
    def test_logged_build_preserves_failure_status(self):
        workflow = (ROOT / '.github/workflows/build-recovery.yml').read_text()
        block = workflow.split('      - name: Build and verify native AERA boot image\n',1)[1].split('      - name:',1)[0]
        self.assertIn('        shell: bash\n', block)
        command = next(line.split('run: ',1)[1] for line in block.splitlines() if 'run: ' in line)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'ci').mkdir()
            (root / 'ci/build.sh').write_text('echo checkout-failed; exit 73\n')
            env = dict(os.environ, AERA_ARTIFACT_DIR=str(root))
            result = subprocess.run(['bash','--noprofile','--norc','-e','-o','pipefail','-c',command],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,73)
            self.assertIn('checkout-failed', (root / 'session.log').read_text())

    def test_build_passes_the_supplied_image_and_module_manifest_before_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin'
            binary.mkdir()
            python = binary / 'python3'
            python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARGUMENT_LOG"\nexit 73\n')
            python.chmod(0o755)
            arguments = root / 'arguments'
            image = root / 'Image'
            env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                       ARGUMENT_LOG=str(arguments), AERA_PREBUILT_KERNEL=str(image),
                       AERA_SOURCE_DIR=str(root / 'source'), AERA_ARTIFACT_DIR=str(root / 'artifacts'))
            result = subprocess.run(['bash', str(ROOT / 'ci/build.sh')], env=env)
            self.assertEqual(result.returncode, 73)
            self.assertEqual(arguments.read_text().splitlines(), [
                str(ROOT / 'tools/kernel_input.py'), str(image), '--module-manifest',
                str(ROOT / 'modules/manifest.json')])
            self.assertFalse((root / 'source').exists())


if __name__ == '__main__':
    unittest.main()
