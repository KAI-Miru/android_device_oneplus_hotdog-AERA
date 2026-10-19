import io
import lzma
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lzma_ramdisk import compress, DICTIONARY_BYTES

TOOL = Path(__file__).resolve().parents[1] / 'tools/lzma_ramdisk.py'


class RamdiskCompressionTests(unittest.TestCase):
    def test_native_stream_is_lossless_legacy_lzma(self):
        raw = bytes(range(256)) * 10000
        output = io.BytesIO()
        compress(io.BytesIO(raw), output)
        encoded = output.getvalue()
        self.assertEqual(struct.unpack_from('<I', encoded, 1)[0], DICTIONARY_BYTES)
        self.assertEqual(lzma.decompress(encoded, format=lzma.FORMAT_ALONE), raw)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Tests the Linux build-tool interpreter')
    def test_android_python_on_path_cannot_replace_lzma_capable_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            android_python = Path(directory) / 'python3'
            android_python.write_text('#!/bin/sh\necho "Android Python has no _lzma" >&2\nexit 77\n')
            android_python.chmod(0o755)
            raw = b'070701' + bytes(range(256)) * 1000
            result = subprocess.run([str(TOOL), '-f', '-c'], input=raw, capture_output=True,
                env=dict(os.environ, PATH=directory), timeout=30, check=True)
            self.assertEqual(struct.unpack_from('<I', result.stdout, 1)[0], DICTIONARY_BYTES)
            self.assertEqual(lzma.decompress(result.stdout, format=lzma.FORMAT_ALONE), raw)


if __name__ == '__main__':
    unittest.main()
