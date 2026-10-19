import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('rsync'), 'Linux rsync restoration')
class RestoreTests(unittest.TestCase):
    def test_identical_build_definitions_keep_timestamps_but_changed_inputs_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source', root / 'target'
            source.mkdir(); target.mkdir()
            for path in (source / 'Android.bp', target / 'Android.bp'):
                path.write_text('soong_namespace {}\n')
            (source / 'kernel').write_bytes(b'new kernel')
            (target / 'kernel').write_bytes(b'old kernel')
            os.utime(target / 'Android.bp', (1000000000, 1000000000))
            stamp = (target / 'Android.bp').stat().st_mtime_ns
            subprocess.run(['rsync', '-rcp', '--delete', str(source) + '/', str(target) + '/'], check=True)
            self.assertEqual((target / 'Android.bp').stat().st_mtime_ns, stamp)
            self.assertEqual((target / 'kernel').read_bytes(), b'new kernel')
