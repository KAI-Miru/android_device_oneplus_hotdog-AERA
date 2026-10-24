"""Exercise actual firmware resolution and TFTP's dropped-privilege storage."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest

import test_wifi_startup as startup

sys.path.insert(0, str(startup.ROOT / 'tools'))
from verify_rfs import verify_rfs_configuration


@unittest.skipUnless(sys.platform.startswith('linux'), 'Isolated Linux shell fixture')
class RfsStorageTests(unittest.TestCase):
    tearDown = startup.WifiStartupTests.tearDown
    run_script = startup.WifiStartupTests.run_script
    events = startup.WifiStartupTests.events

    def setUp(self):
        startup.WifiStartupTests.setUp(self)
        # Real chmod and (where permitted) chown exercise private directory
        # access. A non-root test host maps the requested owner to itself.
        script = startup.MOCK + '''
if name == 'chown' and args[0] == '2903:2903':
    if os.environ.get('TASK_RFS_FAIL_OWNER') == '1':
        sys.exit(1)
    for path in args[1:]:
        os.chown(path, 2903 if os.geteuid() == 0 else os.geteuid(),
                 2903 if os.geteuid() == 0 else os.getegid())
'''
        (self.root / 'bin/chown').write_text(script)
        (self.root / 'firmware/image/wlanmdsp.mbn').write_bytes(b'original firmware fixture')
        (self.root / 'vendor/firmware').mkdir()
        (self.root / 'vendor/firmware/fallback.mbn').write_bytes(b'vendor fixture')

    def storage(self):
        return self.run_script('hotdog-wlan-storage.sh')

    def test_all_stock_links_and_firmware_reads(self):
        self.assertEqual(self.storage().returncode, 0)
        expected = {}
        # These are the original dump's ten subsystem directories, including
        # its intentionally absent mdm/{cdsp,slpi,tn} vendor fallback links.
        for family, subsystem, dump, fallback in (
                ('apq', 'gnss', 'modem', True), ('mdm', 'adsp', 'lpass', True),
                ('mdm', 'cdsp', 'cdsp', False), ('mdm', 'mpss', 'modem', True),
                ('mdm', 'slpi', 'slpi', False), ('mdm', 'tn', 'tn', False),
                ('msm', 'adsp', 'lpass', True), ('msm', 'cdsp', 'cdsp', True),
                ('msm', 'mpss', 'modem', True), ('msm', 'slpi', 'slpi', True)):
            directory = f'{family}/{subsystem}'
            for link, target in (
                    ('hlos', 'mnt/vendor/persist/hlos_rfs/shared'),
                    ('readwrite', f'mnt/vendor/persist/rfs/{directory}'),
                    ('shared', 'mnt/vendor/persist/rfs/shared'),
                    ('ramdumps', f'data/vendor/tombstones/rfs/{dump}'),
                    ('readonly/firmware', 'vendor/firmware_mnt')):
                expected[f'{directory}/{link}'] = str(self.root / target)
            if fallback:
                expected[f'{directory}/readonly/vendor/firmware'] = str(self.root / 'vendor/firmware')
            if subsystem == 'mpss':
                expected[f'{directory}/olog'] = str(self.root / 'data/vendor/olog')
        rfs = self.root / 'vendor/rfs'
        actual = {p.relative_to(rfs).as_posix(): os.readlink(p)
                  for p in rfs.rglob('*') if p.is_symlink()}
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 59)
        for directory in (rfs / 'msm/mpss', rfs / 'msm/adsp'):
            self.assertEqual((directory / 'readonly/firmware/image/wlanmdsp.mbn').read_bytes(),
                             b'original firmware fixture')
            self.assertEqual((directory / 'readonly/vendor/firmware/fallback.mbn').read_bytes(),
                             b'vendor fixture')
        for p in rfs.rglob('*'):
            if not p.is_symlink():
                self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o755)

    def test_private_ram_roots_accept_tftp_writes_without_changing_persist(self):
        seed = self.root / 'mnt/vendor/persist/rfs/calibration'
        seed.write_bytes(b'calibration seed')
        original = {p.relative_to(self.root / 'mnt/vendor/persist').as_posix():
                    (p.stat().st_uid, p.stat().st_gid, p.stat().st_mode)
                    for p in (self.root / 'mnt/vendor/persist').rglob('*')}
        self.assertEqual(self.storage().returncode, 0)
        base = self.root / 'tmp/hotdog-wlan-rfs'
        paths = [base / p for p in ('ramdumps', 'olog', 'rfs', 'hlos_rfs',
                 'ramdumps/modem', 'ramdumps/lpass', 'ramdumps/cdsp',
                 'ramdumps/slpi', 'ramdumps/tn', 'rfs/msm/mpss',
                 'rfs/shared', 'hlos_rfs/shared')]
        for path in paths:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertIn(['chown', '2903:2903', str(path)], self.events())
            if os.geteuid() == 0:
                self.assertEqual((path.stat().st_uid, path.stat().st_gid), (2903, 2903))
        # Open directories as root, then drop to TFTP's actual uid/gid. dir_fd
        # models access through the bind mount without the private /tmp parent.
        writer = '''import os,sys
fds=[os.open(p,os.O_RDONLY|os.O_DIRECTORY) for p in sys.argv[1:]]
if os.geteuid()==0:
    os.setgroups([]);os.setgid(2903);os.setuid(2903)
for fd in fds:
    f=os.open('tftp-probe',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=fd)
    os.write(f,b'RAM');os.close(f)
'''
        result = subprocess.run([sys.executable, '-c', writer, *map(str, paths)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(seed.read_bytes(), b'calibration seed')
        after = {p.relative_to(self.root / 'mnt/vendor/persist').as_posix():
                 (p.stat().st_uid, p.stat().st_gid, p.stat().st_mode)
                 for p in (self.root / 'mnt/vendor/persist').rglob('*')}
        self.assertEqual(original, after)
        self.assertFalse(any(e[0] == 'chown' and '/mnt/vendor/persist/' in e[-1]
                             for e in self.events()))
        self.assertEqual(self.storage().returncode, 0)
        self.assertEqual((base / 'olog/tftp-probe').read_bytes(), b'RAM')

    def test_foreign_vendor_mount_is_rejected_before_layout_or_binds(self):
        with (self.root / 'proc/mounts').open('a') as mounts:
            mounts.write(f'fixture {self.root}/vendor erofs ro 0 0\n')
        self.assertNotEqual(self.storage().returncode, 0)
        self.assertFalse((self.root / 'vendor/rfs').exists())
        self.assertFalse(any(e[0] == 'mount' for e in self.events()))

    def test_wrong_link_and_directory_link_escape_are_rejected(self):
        self.assertEqual(self.storage().returncode, 0)
        link = self.root / 'vendor/rfs/msm/mpss/readonly/firmware'
        link.unlink()
        link.symlink_to(self.root / 'mnt/vendor/persist')
        self.assertNotEqual(self.storage().returncode, 0)
        self.assertEqual(os.readlink(link), str(self.root / 'mnt/vendor/persist'))
        link.unlink()
        link.symlink_to(self.root / 'vendor/firmware_mnt')
        directory = self.root / 'vendor/rfs/msm/mpss/readonly/vendor'
        (directory / 'firmware').unlink()
        directory.rmdir()
        directory.symlink_to(self.root / 'mnt/vendor/persist')
        self.assertNotEqual(self.storage().returncode, 0)
        self.assertFalse((self.root / 'mnt/vendor/persist/firmware').exists())

    def test_ram_link_cannot_redirect_ownership_to_persist(self):
        base = self.root / 'tmp/hotdog-wlan-rfs'
        base.mkdir()
        target = self.root / 'mnt/vendor/persist/rfs'
        before = target.stat()
        (base / 'ramdumps').symlink_to(target)
        self.assertNotEqual(self.storage().returncode, 0)
        self.assertEqual(target.stat().st_uid, before.st_uid)
        self.assertFalse(any(e[0] in ('chown', 'mount') for e in self.events()))

    def test_ownership_failure_prevents_backends_and_radio(self):
        self.env['TASK_RFS_FAIL_OWNER'] = '1'
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        for service in ('hotdog-rmt-storage', 'hotdog-tftp-server', 'hotdog-wlan-firmware'):
            self.assertNotIn(['setprop', 'ctl.start', service], self.events())
        self.assertFalse(any(e[0] == 'insmod' for e in self.events()))
        state = json.loads((self.root / 'properties.json').read_text())
        self.assertEqual(state['sys.hotdog.wlan.prepare'], 'failed')


class RfsImageAuditTests(unittest.TestCase):
    def test_image_audit_rejects_missing_layout_ownership_and_guards(self):
        script = (startup.ROOT / 'recovery/root/system/bin/hotdog-wlan-storage.sh').read_text()
        verify_rfs_configuration(script)
        for old in ('msm mpss modem yes', 'chown 2903:2903 "$base/$name"',
                    'chmod 0700 "$base/$name"', "! grep -q ' /vendor ' /proc/mounts || exit 1",
                    'rfs_link /vendor/firmware_mnt "$dir/readonly/firmware"',
                    '[ "$(readlink "$2")" = "$1" ] || exit 1',
                    '[ -z "$(find "$base" -type l -print)" ] || exit 1'):
            with self.subTest(removed=old), self.assertRaises(ValueError):
                verify_rfs_configuration(script.replace(old, ''))


if __name__ == '__main__':
    unittest.main()
