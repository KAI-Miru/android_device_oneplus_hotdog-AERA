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
