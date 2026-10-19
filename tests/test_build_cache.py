import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildCacheTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('make'), 'Native Linux Make writer')
    def test_identical_configuration_keeps_timestamp_and_changed_architecture_updates(self):
        # This is the pinned native writer fragment, before the host patch.
        original = ('\n$(file >$(SOONG_VARIABLES).tmp,$(json_contents))\n\n'
                    '$(shell mv $(SOONG_VARIABLES).tmp $(SOONG_VARIABLES);)\n\n'
                    'include $(BUILD_SYSTEM)/soong_extra_config.mk\n\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = root / 'core'
            core.mkdir()
            (core / 'soong_config.mk').write_text(original)
            (core / 'soong_extra_config.mk').touch()
            output = root / 'soong.variables'
            (root / 'Makefile').write_text(
                f'BUILD_SYSTEM := {core}\nSOONG_VARIABLES := {output}\n'
                'json_contents := {"Arm32":$(ARM32),"Crypto":true}\n'
                'include core/soong_config.mk\n.PHONY: all\nall:\n\t@true\n')

            def make(value):
                subprocess.run(['make', '--no-print-directory', 'ARM32=' + value], cwd=root,
                               check=True, capture_output=True)

            make('true')
            os.utime(output, ns=(1_000_000_000, 1_000_000_000))
            make('true')
            self.assertNotEqual(output.stat().st_mtime_ns, 1_000_000_000)
            subprocess.run(['git', 'apply', str(ROOT / 'ci/patches/make-config-cache.patch')],
                           cwd=root, check=True, capture_output=True)
            os.utime(output, ns=(1_000_000_000, 1_000_000_000))
            make('true')
            self.assertEqual(output.stat().st_mtime_ns, 1_000_000_000)
            make('false')
            self.assertNotEqual(output.stat().st_mtime_ns, 1_000_000_000)
            self.assertEqual(json.loads(output.read_text()), {'Arm32': False, 'Crypto': True})
            self.assertFalse(output.with_suffix('.variables.tmp').exists())


if __name__ == '__main__':
    unittest.main()
