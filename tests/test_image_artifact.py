import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image_artifact', ROOT / 'ci/verify_image_artifact.py')
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class ImageArtifactTests(unittest.TestCase):
    def fixture(self, root, name='AERA-hotdog-ALPHA-recovery.img'):
        image = root / name
        with image.open('wb') as stream:
            stream.truncate(artifact.IMAGE_BYTES)
        digest = hashlib.sha256()
        with image.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        checksum = digest.hexdigest()
        (root / 'SHA256SUMS').write_text(checksum + '  ' + name + '\n')
        (root / 'image-verification.json').write_text(json.dumps({'sha256': checksum, 'image_bytes': artifact.IMAGE_BYTES}))
        return image

    def test_checksum_only_artifact_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'SHA256SUMS').write_text('0' * 64 + '  AERA-hotdog-ALPHA-recovery.img\n')
            with self.assertRaisesRegex(ValueError, 'checksum-only'):
                artifact.verify(root)

    def test_filename_is_derived_from_the_verified_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = self.fixture(root, 'renamed-dedicated-recovery.img')
            self.assertEqual(artifact.verify(root), image)
            output = root / 'github-output'
            result = subprocess.run([sys.executable, str(ROOT / 'ci/verify_image_artifact.py'), str(root)],
                env=dict(os.environ, GITHUB_OUTPUT=str(output)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), 'image_path=' + str(image) + '\n')

    def test_report_mismatch_and_modified_image_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = self.fixture(root)
            (root / 'image-verification.json').write_text('{"sha256":"wrong","image_bytes":100663296}')
            with self.assertRaisesRegex(ValueError, 'disagree'):
                artifact.verify(root)
            self.fixture(root)
            with image.open('r+b') as stream:
                stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'disagree'):
                artifact.verify(root)

    def test_truncated_extra_and_symlink_images_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = self.fixture(root)
            image.write_bytes(b'truncated')
            with self.assertRaisesRegex(ValueError, '96 MiB'):
                artifact.verify(root)
            self.fixture(root)
            other = root / 'unexpected.img'
            other.touch()
            with self.assertRaisesRegex(ValueError, 'unexpected'):
                artifact.verify(root)
            image.unlink()
            image.symlink_to(other)
            with self.assertRaisesRegex(ValueError, 'checksum-only'):
                artifact.verify(root)


if __name__ == '__main__':
    unittest.main()
