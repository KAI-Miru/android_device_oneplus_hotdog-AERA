from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class HotdogTargetTests(unittest.TestCase):
    def test_compile_and_checkpoint_paths_use_dedicated_recovery(self):
        compile = (ROOT/'ci/compile.sh').read_text()
        self.assertIn('lunch twrp_hotdog-bp2a-eng',compile)
        self.assertIn('adbd recoveryimage',compile)
        self.assertNotIn('bootimage',compile)
        for path in ('ci/build.sh','ci/save-checkpoint.sh','tools/verify_prepared_environment.py'):
            source = (ROOT/path).read_text()
            self.assertIn('out/target/product/hotdog/recovery.img',source)
            self.assertNotIn('out/target/product/hotdog/boot.img',source)


if __name__ == '__main__':
    unittest.main()
