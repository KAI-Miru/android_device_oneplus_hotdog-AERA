import sys
import shlex
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_usb import verify_usb_configuration


class UsbTests(unittest.TestCase):
    def setUp(self):
        self.script = (ROOT / 'recovery/root/init.recovery.usb.rc').read_bytes()

    def test_native_mtp_adb_identity_and_functions(self):
        self.assertEqual(verify_usb_configuration(self.script)['mtp_adb_pid'], '4ee2')

    def test_sideload_keeps_normal_adbd_stopped(self):
        gadget = UsbActions(self.script)
        # Recovery stops normal adbd through native "none" cleanup, forks
        # minadbd, then selects sideload. Only minadbd may own its endpoints.
        gadget.set('sys.usb.config', 'none')
        gadget.commands.clear()
        gadget.set('sys.usb.config', 'sideload')
        gadget.set('sys.usb.ffs.ready', '1')
        self.assertNotIn(['start', 'adbd'], gadget.commands)
        self.assertNotIn(['restart', 'adbd'], gadget.commands)
        self.assertEqual(gadget.commands, [])  # Native init owns the binding.

    def test_previous_sideload_rule_reproduces_normal_adbd_restart(self):
        old = self.script + (
            b'\non property:sys.usb.config=sideload && property:sys.usb.configfs=1\n'
            b'    start adbd\n')
        gadget = UsbActions(old)
        gadget.set('sys.usb.config', 'sideload')
        self.assertIn(['start', 'adbd'], gadget.commands)
        with self.assertRaisesRegex(ValueError, 'sideload belongs to minadbd'):
            verify_usb_configuration(old)

    def test_rejects_normal_adbd_start_without_an_explicit_adb_profile(self):
        for trigger in ('property:sys.usb.config=sideload && property:sys.usb.configfs=1',
                        'property:sys.usb.configfs=1 && property:sys.usb.config=sideload',
                        'property:sys.usb.ffs.ready=1', 'fs'):
            for command in ('start adbd', 'restart adbd', 'exec_start adbd',
                            'setprop ctl.start adbd', 'setprop ctl.restart adbd'):
                with self.subTest(trigger=trigger, command=command):
                    bad = self.script + f'\non {trigger}\n    {command}\n'.encode()
                    with self.assertRaisesRegex(ValueError, 'sideload belongs to minadbd'):
                        verify_usb_configuration(bad)

    def test_duplicate_init_actions_cannot_hide_an_adbd_start(self):
        bad = self.script + (
            b'\non property:sys.usb.ffs.ready=1\n    start adbd\n'
            b'\non property:sys.usb.ffs.ready=1\n    setprop test.ready 1\n')
        with self.assertRaisesRegex(ValueError, 'sideload belongs to minadbd'):
            verify_usb_configuration(bad)

    def test_return_from_sideload_preserves_mtp_adb_startup(self):
        gadget = UsbActions(self.script)
        gadget.set('sys.usb.config', 'sideload')
        gadget.set('sys.usb.ffs.ready', '1')  # minadbd descriptors are ready.
        self.assertNotIn(['start', 'adbd'], gadget.commands)
        gadget.set('sys.usb.config', 'none')
        gadget.set('sys.usb.ffs.ready', '0')  # Native cleanup after minadbd exits.
        gadget.set('sys.usb.config', 'mtp,adb')
        self.assertEqual(gadget.commands.count(['start', 'adbd']), 1)
        self.assertFalse(gadget.bound)
        gadget.set('sys.usb.ffs.ready', '1')
        self.assertFalse(gadget.bound)
        gadget.set('sys.usb.ffs.mtp.ready', '1')
        self.assertTrue(gadget.bound)
        self.assertEqual(gadget.properties['sys.usb.state'], 'mtp,adb')

    def test_rejects_mismatched_identity_and_missing_adb_function(self):
        changes = ((b'0x4ee2', b'0x9012'), (b'0x18d1', b'0x05c6'),
                   (b'functions/ffs.adb', b'functions/ffs.mtp'),
                   (b'property:sys.usb.ffs.ready=1', b'property:sys.usb.ffs.ready=0'),
                   (b' && property:sys.usb.ffs.mtp.ready=1', b''),
                   (b'    start adbd', b'    stop adbd'),
                   (b'    write /config/usb_gadget/g1/UDC ${sys.usb.controller}',
                    b'    write /config/usb_gadget/g1/UDC "none"'))
        for old, new in changes:
            with self.subTest(old=old), self.assertRaises(ValueError):
                verify_usb_configuration(self.script.replace(old, new))

    def test_mtp_adb_waits_for_both_descriptor_orders(self):
        for first, second in (('sys.usb.ffs.ready', 'sys.usb.ffs.mtp.ready'),
                              ('sys.usb.ffs.mtp.ready', 'sys.usb.ffs.ready')):
            with self.subTest(first=first):
                gadget = UsbActions(self.script)
                gadget.set('sys.usb.config', 'mtp,adb')
                self.assertEqual(gadget.bound, False)
                self.assertIn(['start', 'adbd'], gadget.commands)
                gadget.set(first, '1')
                self.assertEqual(gadget.bound, False)
                gadget.set(second, '1')
                self.assertEqual(gadget.bound, True)
                self.assertEqual(gadget.properties['sys.usb.state'], 'mtp,adb')

    def test_mtp_only_waits_for_its_descriptors(self):
        gadget = UsbActions(self.script)
        gadget.set('sys.usb.config', 'mtp')
        self.assertFalse(gadget.bound)
        gadget.set('sys.usb.ffs.mtp.ready', '1')
        self.assertTrue(gadget.bound)

    def test_previous_adb_only_gate_reproduces_failed_bind(self):
        old = self.script.replace(b' && property:sys.usb.ffs.mtp.ready=1', b'')
        gadget = UsbActions(old)
        gadget.set('sys.usb.config', 'mtp,adb')
        gadget.set('sys.usb.ffs.ready', '1')
        self.assertFalse(gadget.bound)
        self.assertEqual(gadget.failed_binds, 1)
        gadget.set('sys.usb.ffs.mtp.ready', '1')
        self.assertFalse(gadget.bound)  # No matching property trigger retries it.

    def test_ready_handler_leaves_disconnect_to_native_cleanup(self):
        gadget = UsbActions(self.script)
        gadget.set('sys.usb.config', 'mtp,adb')
        gadget.set('sys.usb.ffs.ready', '1')
        gadget.set('sys.usb.ffs.mtp.ready', '1')
        self.assertNotIn(['write', '/config/usb_gadget/g1/UDC', 'none'], gadget.commands)
        bad = self.script.replace(
            b'    write /config/usb_gadget/g1/UDC ${sys.usb.controller}',
            b'    write /config/usb_gadget/g1/UDC "none"\n'
            b'    write /config/usb_gadget/g1/UDC ${sys.usb.controller}')
        with self.assertRaisesRegex(ValueError, 'must not invalidate'):
            verify_usb_configuration(bad)


class UsbActions:
    """Replay property-triggered RC actions with FunctionFS bind prerequisites."""

    def __init__(self, script):
        self.rules = []
        for line in script.decode('utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('on '):
                conditions = {}
                if all(term.startswith('property:') for term in line[3:].split(' && ')):
                    conditions = dict(term[9:].split('=', 1)
                                      for term in line[3:].split(' && '))
                self.rules.append((conditions, []))
            elif self.rules:
                self.rules[-1][1].append(shlex.split(line))
        self.properties = {'sys.usb.configfs': '1', 'sys.usb.ffs.ready': '0',
                           'sys.usb.ffs.mtp.ready': '0', 'sys.usb.controller': 'controller'}
        self.commands = []
        self.bound = False
        self.failed_binds = 0

    def set(self, key, value):
        if self.properties.get(key) == value:
            return
        self.properties[key] = value
        for conditions, commands in self.rules:
            if key not in conditions or not all(self.properties.get(k) == v
                                                for k, v in conditions.items()):
                continue
            for command in commands:
                self.commands.append(command)
                if command[0] == 'setprop':
                    new_value = command[2].replace('${sys.usb.config}',
                                                   self.properties['sys.usb.config'])
                    self.set(command[1], new_value)
                elif command[:2] == ['write', '/config/usb_gadget/g1/UDC']:
                    if command[2] == 'none':
                        self.bound = False
                    else:
                        required = ['sys.usb.ffs.mtp.ready']
                        if self.properties['sys.usb.config'] == 'mtp,adb':
                            required.append('sys.usb.ffs.ready')
                        self.bound = all(self.properties.get(prop) == '1' for prop in required)
                        self.failed_binds += not self.bound


if __name__ == '__main__':
    unittest.main()
