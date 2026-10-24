"""Regressions for complete stock duration firmware and EROFS System probing."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from verify_haptics import haptic_inputs, verify_haptic_runtime, verify_haptic_source
from verify_mount_options import verify_system_mount_options


class HapticDurationTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads((ROOT / 'tools/haptic-source.json').read_text())
        self.entries = {name: (0o100644, (ROOT / 'proprietary' / name).read_bytes())
                        for name in self.source['files']}

    def test_all_duration_requests_in_bundled_kernel_are_packaged(self):
        requested = set(name.decode() for name in re.findall(
            rb'[0-9]+ms_RTP_[0-9]+Hz\.bin', (ROOT / 'prebuilt/kernel').read_bytes()))
        expected = {f'{duration}ms_RTP_{hz}Hz.bin'
                    for duration in range(20, 501, 20) for hz in (166, 170, 174)}
        self.assertEqual(requested, expected)
        self.assertTrue({'vendor/firmware/' + name for name in requested} <= self.entries.keys())
        result = verify_haptic_runtime(self.entries)
        self.assertEqual(result['rtp_frequencies_hz'], [166, 170, 174])

    def test_every_duration_is_required_in_actual_ramdisk(self):
        for name in self.entries:
            if 'ms_RTP_' not in name: continue
            changed = dict(self.entries)
            del changed[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                verify_haptic_runtime(changed)

    def test_wrong_waveform_and_symlink_are_rejected(self):
        for value in ((0o100644, b'wrong duration'), (0o120777, b'40ms_RTP_170Hz.bin')):
            changed = dict(self.entries)
            changed['vendor/firmware/160ms_RTP_170Hz.bin'] = value
            with self.assertRaises(ValueError): verify_haptic_runtime(changed)

    def test_pruned_manifest_cannot_hide_missing_duration(self):
        changed = copy.deepcopy(self.source)
        del changed['files']['vendor/firmware/500ms_RTP_174Hz.bin']
        with self.assertRaises(ValueError): verify_haptic_source(changed)

    def test_exact_stock_source_required_for_import(self):
        with tempfile.TemporaryDirectory() as temp:
            dump = Path(temp) / self.source['source_dump']
            for name, (_, data) in self.entries.items():
                target = dump / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.assertEqual(haptic_inputs(dump, self.source),
                             {name: data for name, (_, data) in self.entries.items()})
            with self.assertRaises(ValueError): haptic_inputs(Path(temp) / 'wrong-model', self.source)
            (dump / 'vendor/firmware/160ms_RTP_170Hz.bin').write_bytes(b'wrong')
            with self.assertRaises(ValueError): haptic_inputs(dump, self.source)

    def test_manifest_and_native_copy_rules_keep_stock_provenance(self):
        manifest = json.loads((ROOT / 'proprietary/manifest.json').read_text())
        self.assertEqual(manifest['haptic_source'], self.source)
        copies = (ROOT / 'proprietary-files.mk').read_text()
        for name, identity in self.source['files'].items():
            record = manifest['files'][name]
            self.assertEqual(record['source_dump'], self.source['source_dump'])
            self.assertEqual(record['sha256'], identity['sha256'])
            self.assertIn(f'$(LOCAL_PATH)/proprietary/{name}:$(TARGET_COPY_OUT_RECOVERY)/root/{name}', copies)


class SystemMountTests(unittest.TestCase):
    def test_ext4_and_erofs_probe_share_only_read_only_options(self):
        text = (ROOT / 'recovery/root/system/etc/recovery.fstab').read_text()
        self.assertEqual(verify_system_mount_options(text)['system_mount_options'], 'ro')
        for options in ('ro,barrier=1,discard', 'rw', 'ro,discard'):
            changed = re.sub(r'(\s(?:/|/system|/system_root)\s+ext4\s+)ro(\s)',
                             lambda match: match[1] + options + match[2], text)
            with self.subTest(options=options), self.assertRaises(ValueError):
                verify_system_mount_options(changed)

    def test_duplicate_system_rows_are_rejected(self):
        with self.assertRaises(ValueError):
            verify_system_mount_options('system /system ext4 ro wait\nsystem /system erofs ro wait\n')


if __name__ == '__main__': unittest.main()
