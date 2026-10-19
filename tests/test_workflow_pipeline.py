import os
from pathlib import Path
import subprocess
import sys
import unittest
import tempfile

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux shell execution")
class WorkflowPipelineTests(unittest.TestCase):
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
