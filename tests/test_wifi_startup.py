import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_wifi import verify_startup_configuration

MOCK = '''#!/usr/bin/env python3
import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ['TASK_WLAN_TEST_ROOT'])
name = Path(sys.argv[0]).name
args = sys.argv[1:]
state_file = root / 'properties.json'
state = json.loads(state_file.read_text())
with (root / 'events.jsonl').open('a') as events:
    events.write(json.dumps([name, *args]) + '\\n')
if name == 'uname':
    print(os.environ.get('TASK_WLAN_TEST_KERNEL', '4.14.357-openela-ColorOS15-ci59+'))
elif name == 'mount' and args[-2:] == [str(root / 'firmware'), str(root / 'vendor/firmware_mnt')]:
    shutil.copytree(root / 'firmware', root / 'vendor/firmware_mnt', dirs_exist_ok=True)
elif name == 'mount':
    source, target = map(Path, args[-2:])
    relative = source.relative_to(root / 'tmp').as_posix()
    with (root / 'proc/self/mountinfo').open('a') as mounts:
        mounts.write('1 0 0:0 /' + relative + ' ' + str(target) + ' rw - tmpfs none rw\\n')
elif name == 'setprop':
    if args[0] == 'ctl.start':
        if args[1] == 'hotdog-pd-mapper':
            if not (root / 'vendor/firmware_mnt/image/modemuw.jsn').is_file():
                sys.exit(9)
        state['init.svc.' + args[1]] = 'stopped' if args[1] == os.environ.get('TASK_WLAN_FAIL_SERVICE') else 'running'
    else:
        state[args[0]] = args[1]
    state_file.write_text(json.dumps(state))
elif name == 'getprop':
    print(state.get(args[0], ''))
elif name == 'chown' and args[0] == 'wifi:wifi':
    if os.environ.get('TASK_WLAN_FAIL_CONFIG_OWNER') == '1':
        sys.exit(1)
    state['fixture.wifi-owned-config'] = args[1]
    state_file.write_text(json.dumps(state))
elif name == 'wpa_supplicant':
    config = Path(next(arg[2:] for arg in args if arg.startswith('-c')))
    if state.get('fixture.wifi-owned-config') != str(config) or config.stat().st_mode & 0o777 != 0o600:
        sys.exit(13)
'''


@unittest.skipUnless(sys.platform.startswith('linux'), 'Runs shell scripts in an isolated Linux fixture')
class WifiStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for path in ('data/vendor/wifi', 'vendor', 'firmware/image',
                     'tmp', 'proc/self', 'sys/class/net', 'system/lib/modules/msmnile', 'system/bin', 'system/etc', 'bin',
                     'mnt/vendor/persist/rfs', 'mnt/vendor/persist/hlos_rfs', 'data/vendor/tombstones/rfs', 'data/vendor/olog'):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        (self.root / 'firmware/image/modemuw.jsn').write_text('{"sr_service":[{"provider":"wlan","service":"fw"}]}')
        (self.root / 'vendor/firmware_mnt').symlink_to(self.root / 'firmware', target_is_directory=True)
        (self.root / 'system/lib/modules/msmnile/qca_cld3_wlan.ko').write_text('module supplied by fixture')
        (self.root / 'system/etc/hotdog-wpa_supplicant.conf').write_text('ctrl_interface=DIR=/tmp/recovery/sockets GROUP=wifi\n')
        (self.root / 'proc/mounts').write_text(f'fixture {self.root}/mnt/vendor/persist ext4 ro,seclabel 0 0\n')
        (self.root / 'proc/self/mountinfo').touch()
        (self.root / 'proc/modules').touch()
        (self.root / 'properties.json').write_text('{"sys.hotdog.wlan.prepare":"preparing"}')
        for name in ('uname', 'mount', 'chown', 'sleep', 'setprop', 'getprop', 'insmod'):
            path = self.root / 'bin' / name
            path.write_text(MOCK)
            path.chmod(0o755)
        supplicant = self.root / 'system/bin/wpa_supplicant'
        supplicant.write_text(MOCK)
        supplicant.chmod(0o755)
        (self.root / 'system/bin/sh').symlink_to('/bin/sh')
        self.env = dict(os.environ, TASK_WLAN_TEST_ROOT=str(self.root), PATH=str(self.root / 'bin') + ':' + os.environ['PATH'])

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, name):
        for entry in ('hotdog-wlan-domains.sh', 'hotdog-wlan-prepare.sh', 'hotdog-wpa-supplicant.sh', 'hotdog-wlan-storage.sh'):
            text = (ROOT / 'recovery/root/system/bin' / entry).read_text()
            text = re.sub(r'(?<![\w/.-])/(system|vendor|firmware|data|tmp|proc|sys|mnt)(?=/|\b)',
                          lambda match: str(self.root) + match.group(), text)
            (self.root / 'system/bin' / entry).write_text(text)
        script = self.root / 'system/bin' / name
        # A failed service exhausts 100 polls, each launching fixture processes.
        # Allow for host load without changing the device's bounded wait.
        return subprocess.run(['/bin/sh', str(script)], env=self.env, timeout=30)

    def events(self):
        path = self.root / 'events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_ramdisk_firmware_mapper_precedes_modem_reference(self):
        self.assertEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        events = self.events()
        self.assertFalse(any(event[0] == 'mount' and event[-1].endswith('/vendor/firmware_mnt') for event in events))
        starts = [event[2] for event in events if event[:2] == ['setprop', 'ctl.start']]
        self.assertEqual(starts, ['hotdog-qrtr-ns', 'hotdog-pd-mapper', 'hotdog-rmt-storage', 'hotdog-tftp-server', 'hotdog-wlan-firmware', 'hotdog-cnss-daemon'])
        mapper = events.index(['setprop', 'ctl.start', 'hotdog-pd-mapper'])
        self.assertLess(mapper, next(i for i, event in enumerate(events) if event[0] == 'insmod'))
        self.assertEqual(json.loads((self.root / 'properties.json').read_text())['sys.hotdog.wlan.prepare'], 'ready')

    def test_missing_descriptor_fails_before_power_or_module_loading(self):
        (self.root / 'firmware/image/modemuw.jsn').unlink()
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertFalse(any(event[0] == 'insmod' or event[:2] == ['setprop', 'ctl.start'] for event in self.events()))
        self.assertEqual(json.loads((self.root / 'properties.json').read_text())['sys.hotdog.wlan.prepare'], 'failed')

    def test_boot_domain_registration_keeps_radio_power_off(self):
        self.assertEqual(self.run_script('hotdog-wlan-domains.sh').returncode, 0)
        starts = [event[2] for event in self.events() if event[:2] == ['setprop', 'ctl.start']]
        self.assertEqual(starts, ['hotdog-qrtr-ns', 'hotdog-pd-mapper'])
        self.assertFalse(any(event[0] == 'insmod' for event in self.events()))

    def test_mounted_vendor_is_not_pinned_by_a_child_firmware_bind(self):
        (self.root / 'proc/mounts').write_text(f'fixture {self.root}/vendor erofs ro 0 0\n')
        self.assertNotEqual(self.run_script('hotdog-wlan-domains.sh').returncode, 0)
        self.assertFalse(any(event[0] == 'mount' or event[:2] == ['setprop', 'ctl.start'] for event in self.events()))

    def test_ready_property_does_not_skip_missing_firmware(self):
        (self.root / 'properties.json').write_text('{"sys.hotdog.wlan.domains":"ready"}')
        (self.root / 'vendor/firmware_mnt').unlink()
        (self.root / 'vendor/firmware_mnt').mkdir()
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertNotIn(['setprop', 'ctl.start', 'hotdog-wlan-firmware'], self.events())

    def test_failed_mapper_does_not_start_modem_or_load_module(self):
        self.env['TASK_WLAN_FAIL_SERVICE'] = 'hotdog-pd-mapper'
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertNotIn(['setprop', 'ctl.start', 'hotdog-wlan-firmware'], self.events())
        self.assertFalse(any(event[0] == 'insmod' for event in self.events()))

    def test_wrong_kernel_fails_before_service_changes(self):
        self.env['TASK_WLAN_TEST_KERNEL'] = 'wrong'
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertFalse(any(event[:2] == ['setprop', 'ctl.start'] for event in self.events()))

    def test_supplicant_exits_on_preparation_failure(self):
        (self.root / 'properties.json').write_text('{"sys.hotdog.wlan.prepare":"failed"}')
        self.assertNotEqual(self.run_script('hotdog-wpa-supplicant.sh').returncode, 0)
        self.assertFalse(any(event[0] == 'wpa_supplicant' for event in self.events()))

    def test_native_supplicant_can_read_private_new_config(self):
        (self.root / 'sys/class/net/wlan0').mkdir()
        self.assertEqual(self.run_script('hotdog-wpa-supplicant.sh').returncode, 0)
        self.assertTrue(any(event[0] == 'wpa_supplicant' for event in self.events()))

    def test_native_supplicant_repairs_existing_root_only_config(self):
        (self.root / 'sys/class/net/wlan0').mkdir()
        config = self.root / 'tmp/hotdog-wpa_supplicant.conf'
        config.write_text('ctrl_interface=DIR=/tmp/recovery/sockets GROUP=wifi\n')
        config.chmod(0o600)
        self.assertEqual(self.run_script('hotdog-wpa-supplicant.sh').returncode, 0)

    def test_config_owner_failure_prevents_supplicant_start(self):
        (self.root / 'sys/class/net/wlan0').mkdir()
        self.env['TASK_WLAN_FAIL_CONFIG_OWNER'] = '1'
        self.assertNotEqual(self.run_script('hotdog-wpa-supplicant.sh').returncode, 0)
        self.assertFalse(any(event[0] == 'wpa_supplicant' for event in self.events()))

    def test_writable_persist_keeps_rfs_writes_in_ram(self):
        mounts = self.root / 'proc/mounts'
        mounts.write_text(mounts.read_text().replace('ext4 ro,seclabel', 'ext4 rw,seclabel'))
        original = self.root / 'mnt/vendor/persist/rfs/fixture'
        original.write_text('calibration seed')
        self.assertEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertIn(['setprop', 'ctl.start', 'hotdog-rmt-storage'], self.events())
        self.assertIn(['setprop', 'ctl.start', 'hotdog-tftp-server'], self.events())
        mirror = self.root / 'tmp/hotdog-wlan-rfs/rfs/fixture'
        self.assertEqual(mirror.read_text(), 'calibration seed')
        mirror.write_text('RAM state')
        self.assertEqual(original.read_text(), 'calibration seed')
        targets = {str(self.root / name) for name in (
            'mnt/vendor/persist/rfs', 'mnt/vendor/persist/hlos_rfs',
            'data/vendor/tombstones/rfs', 'data/vendor/olog')}
        binds = [event for event in self.events()
                 if event[0] == 'mount' and event[-1] in targets]
        self.assertEqual({event[-1] for event in binds}, targets)
        self.assertEqual(len(binds), 4)
        for event in binds:
            self.assertEqual(event[1:3], ['-o', 'bind'])
            self.assertTrue(event[-2].startswith(str(self.root / 'tmp/hotdog-wlan-rfs') + '/'))

    def test_absent_persist_still_prevents_backend_start(self):
        (self.root / 'proc/mounts').write_text('')
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertNotIn(['setprop', 'ctl.start', 'hotdog-rmt-storage'], self.events())
        self.assertNotIn(['setprop', 'ctl.start', 'hotdog-tftp-server'], self.events())

    def test_foreign_rfs_mount_is_not_hidden(self):
        target = self.root / 'mnt/vendor/persist/rfs'
        (self.root / 'proc/self/mountinfo').write_text(f'1 0 0:0 /foreign {target} rw - tmpfs none rw\n')
        self.assertNotEqual(self.run_script('hotdog-wlan-storage.sh').returncode, 0)
        self.assertFalse(any(event[0] == 'mount' for event in self.events()))

    def test_radio_cycles_reuse_ram_rfs_without_changing_persist(self):
        original = self.root / 'mnt/vendor/persist/rfs/fixture'
        original.write_text('fixture seed')
        self.assertEqual(self.run_script('hotdog-wlan-storage.sh').returncode, 0)
        mirror = self.root / 'tmp/hotdog-wlan-rfs/rfs/fixture'
        self.assertEqual(mirror.read_text(), 'fixture seed')
        mirror.write_text('RAM runtime state')
        self.assertEqual(self.run_script('hotdog-wlan-storage.sh').returncode, 0)
        self.assertEqual(mirror.read_text(), 'RAM runtime state')
        self.assertEqual(original.read_text(), 'fixture seed')
        self.assertEqual(sum(event[0] == 'mount' for event in self.events()), 4)

    def test_failed_stock_backend_prevents_modem_power(self):
        self.env['TASK_WLAN_FAIL_SERVICE'] = 'hotdog-rmt-storage'
        self.assertNotEqual(self.run_script('hotdog-wlan-prepare.sh').returncode, 0)
        self.assertNotIn(['setprop', 'ctl.start', 'hotdog-wlan-firmware'], self.events())
        self.assertFalse(any(event[0] == 'insmod' for event in self.events()))

    def test_image_rejects_raced_mapper_start_and_automatic_retry(self):
        entries = {name: (0o100644, (ROOT / 'recovery/root' / name).read_bytes()) for name in
                   ('init.recovery.wifi.rc', 'system/bin/hotdog-wlan-domains.sh', 'system/bin/hotdog-wlan-prepare.sh', 'system/bin/hotdog-wpa-supplicant.sh',
                    'system/bin/hotdog-wlan-storage.sh', 'system/etc/hotdog-wpa_supplicant.conf')}
        verify_startup_configuration(entries)
        for old, new in ((b'    start hotdog-wlan-prepare', b'    start hotdog-pd-mapper\n    start hotdog-wlan-prepare'),
                         (b'    oneshot\n    seclabel', b'    seclabel')):
            changed = dict(entries)
            mode, script = entries['init.recovery.wifi.rc']
            changed['init.recovery.wifi.rc'] = (mode, script.replace(old, new))
            with self.assertRaises(ValueError):
                verify_startup_configuration(changed)
        changed = dict(entries)
        mode, script = entries['init.recovery.wifi.rc']
        changed['init.recovery.wifi.rc'] = (mode, script.replace(b'    stop hotdog-wlan-prepare', b'    stop hotdog-qrtr-ns\n    stop hotdog-wlan-prepare'))
        with self.assertRaises(ValueError):
            verify_startup_configuration(changed)


if __name__ == '__main__':
    unittest.main()
