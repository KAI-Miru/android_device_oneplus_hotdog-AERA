import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_image import verify_screen_lock_configuration


class ScreenLockImageTests(unittest.TestCase):
    def test_timeout_and_android_bouncer_are_required(self):
        strings = (b'display suspended after inactivity', b'Use Android screen lock',
                   b'/system/locksettings.db', b'user-gk-authentication', b'weaver-key',
                   b'Checking Android credential...', b'twrp.user.0.decrypt')
        binary = b'\0'.join(strings)
        result = verify_screen_lock_configuration(binary)
        self.assertFalse(result['device_blank_wake_and_credential_tested'])
        with self.assertRaises(ValueError):
            verify_screen_lock_configuration(binary + b'AERA-SCREEN-LOCK-1')
        for marker in strings:
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                verify_screen_lock_configuration(binary.replace(marker, b''))


if __name__ == '__main__':
    unittest.main()
