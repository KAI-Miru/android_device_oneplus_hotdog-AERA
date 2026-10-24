import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux shell execution")
class WorkflowPipelineTests(unittest.TestCase):
    def test_both_upload_paths_require_the_actual_verified_image(self):
        workflow = (ROOT / '.github/workflows/build-recovery.yml').read_text()
        blocks = workflow.split('      - name: Check required image artifact\n')[1:]
        self.assertEqual(len(blocks), 2)  # Cold build and prepared build.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / 'runner/ci'
            scripts.mkdir(parents=True)
            (scripts / 'verify_image_artifact.py').write_bytes((ROOT / 'ci/verify_image_artifact.py').read_bytes())
            artifacts = root / 'aera-artifacts'
            artifacts.mkdir()
            (artifacts / 'SHA256SUMS').write_text('0' * 64 + '  AERA-hotdog-ALPHA-recovery.img\n')
            for block in blocks:
                check, upload = block.split('      - name: Upload verified device-test image\n', 1)
                command = next(line.split('run: ', 1)[1] for line in check.splitlines() if 'run: ' in line)
                result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', command], cwd=root,
                    env=dict(os.environ, RUNNER_TEMP=str(root)), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('checksum-only', result.stderr)
                upload = upload.split('      - name:', 1)[0]
                self.assertIn('${{ steps.image-artifact.outputs.image_path }}', upload)
                self.assertNotIn('ALPHA-boot.img', upload)

    def test_workflows_require_only_bundled_kernel_inputs(self):
        for name in ('build-recovery.yml', 'prepare-builder.yml'):
            workflow = (ROOT / '.github/workflows' / name).read_text()
            for obsolete in ('kernel_url', 'kernel_sha256', 'AERA_KERNEL_ARTIFACT_URL',
                             'KERNEL_INPUT_URL', 'AERA_PREBUILT_KERNEL', 'AERA_KERNEL_SHA256'):
                self.assertNotIn(obsolete, workflow)
            self.assertIn('uses: ./runner/.github/actions/supply-image', workflow)
        action = (ROOT / '.github/actions/supply-image/action.yml').read_text()
        self.assertIn('tools/kernel_input.py', action)
        self.assertNotIn('curl ', action)
        self.assertNotIn('sha256:', action)
        for name in ('build.sh', 'use-prepared.sh'):
            script = (ROOT / 'ci' / name).read_text()
            self.assertIn('tools/kernel_input.py', script)
            self.assertNotIn('AERA_PREBUILT_KERNEL', script)
            self.assertNotIn('retained_image.py', script)

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


if __name__ == "__main__":
    unittest.main()
