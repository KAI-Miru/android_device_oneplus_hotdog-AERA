"""Prevent reintroducing the port's incompatible oembackup/CNV daemon."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import import_vendor
import verify_rmt_storage


class StockRemoteStorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = json.loads((ROOT / 'tools/rmt-storage-source.json').read_text())
        cls.name = cls.source['destination']
        cls.data = (ROOT / 'proprietary' / cls.name).read_bytes()

    def tree(self, root):
        for name in ('tools', 'proprietary/system/bin'):
            (root / name).mkdir(parents=True)
        (root / 'tools/rmt-storage-source.json').write_text(json.dumps(self.source))
        (root / 'proprietary' / self.name).write_bytes(self.data)
        record = {key: self.source[key] for key in ('source_dump', 'source', 'bytes', 'sha256')}
        record.update(verify_rmt_storage.verify_blob(self.data, self.source))
        manifest = {'rmt_storage_source': copy.deepcopy(self.source), 'files': {self.name: record}}
        (root / 'proprietary/manifest.json').write_text(json.dumps(manifest))
        return manifest

    def test_exact_original_stock_binary_is_bundled_and_executable_in_image(self):
        self.assertEqual(len(self.data), 43504)
        self.assertEqual(hashlib.sha256(self.data).hexdigest(),
                         '380528b7f8c8692fbef0dde678ecaec865981c09bbe9ccbe918449229cfa8bf7')
        self.assertNotIn(b'oembackup', self.data)
        self.assertNotIn(b'oppo_nv_client_thread', self.data)
        self.assertEqual(verify_rmt_storage.verify_tree(ROOT), self.source)
        report = verify_rmt_storage.verify_runtime({self.name: (0o100755, self.data)})
        self.assertEqual(report['shared_memory'], 'rmtfs')

    def test_missing_nonexecutable_and_symlink_runtime_are_rejected(self):
        for entries in ({}, {self.name: (0o100644, self.data)},
                        {self.name: (0o120777, b'/vendor/bin/rmt_storage')}):
            with self.subTest(entries=list(entries)), self.assertRaisesRegex(ValueError, 'regular executable'):
                verify_rmt_storage.verify_runtime(entries)

    def test_runtime_rejects_the_port_or_a_modified_stock_binary(self):
        for data in (b'\x7fELF incompatible port oembackup\0', self.data[:-1] + bytes([self.data[-1] ^ 1])):
            with self.subTest(size=len(data)), self.assertRaisesRegex(ValueError, 'pinned stock'):
                verify_rmt_storage.verify_runtime({self.name: (0o100755, data)})

    def test_image_wlan_verifier_enforces_stock_identity_independently(self):
        from verify_wifi import verify_runtime
        with self.assertRaisesRegex(ValueError, 'pinned stock'):
            verify_runtime({self.name: (0o100755, self.data + b'oembackup\0')}, {})

    def test_regenerating_vendor_manifest_cannot_approve_replaced_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.tree(root)
            changed = self.data + b'oembackup\0'
            (root / 'proprietary' / self.name).write_bytes(changed)
            manifest['files'][self.name].update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
            (root / 'proprietary/manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'provenance differs'):
                verify_rmt_storage.verify_tree(root)

    def test_tree_rejects_missing_or_port_source_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.tree(root)
            for kind in ('missing', 'port'):
                changed = copy.deepcopy(manifest)
                if kind == 'missing':
                    changed.pop('rmt_storage_source')
                else:
                    changed['files'][self.name]['source_dump'] = 'C15_PORT_GUAC_4G'
                (root / 'proprietary/manifest.json').write_text(json.dumps(changed))
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'provenance'):
                    verify_rmt_storage.verify_tree(root)

    def test_import_requires_exact_stock_input_without_port_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stock = root / self.source['source_dump']
            port = root / 'C15_PORT_GUAC_4G'
            for dump in (stock, port):
                path = dump / self.source['source']
                path.parent.mkdir(parents=True)
                path.write_bytes(self.data)
            self.assertEqual(verify_rmt_storage.stock_input(stock, self.source), self.data)
            with self.assertRaisesRegex(ValueError, 'must come from'):
                verify_rmt_storage.stock_input(port, self.source)
            (stock / self.source['source']).unlink()
            with self.assertRaises(FileNotFoundError):
                verify_rmt_storage.stock_input(stock, self.source)
            (stock / self.source['source']).write_bytes(self.data[:-1])
            with self.assertRaisesRegex(ValueError, 'pinned stock'):
                verify_rmt_storage.stock_input(stock, self.source)

    def test_importer_prioritizes_stock_even_if_generic_port_seed_returns(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, port = base / 'repo', base / 'C15_PORT_GUAC_4G'
            stock, gpu, official = base / self.source['source_dump'], base / '7Pro_H40', base / 'official'
            for path in (root / 'tools', root / 'proprietary', port / 'vendor/lib64', gpu):
                path.mkdir(parents=True, exist_ok=True)
            fixture_elf = b'\x7fELF' + bytes(64)
            crypto_name = 'vendor/lib64/hw/android.hardware.gatekeeper@1.0-impl-qti.so'
            seeds = {'vendor/bin/rmt_storage': self.name, 'vendor/bin/tftp_server': 'system/bin/tftp_server'}
            configs = {
                'vendor-seeds.json': seeds,
                'rmt-storage-source.json': self.source,
                'official-crypto-source.json': {'repository': 'https://example.invalid/crypto',
                    'commit': '1' * 40, 'seeds': {crypto_name: crypto_name}},
                'gpu-source.json': {'source_dump': '7Pro_H40', 'seeds': {}},
                'haptic-source.json': {'source_dump': '7Pro_H40', 'files': {}},
            }
            for name, config in configs.items():
                (root / 'tools' / name).write_text(json.dumps(config))
            (root / 'proprietary/manifest.json').write_text('{"files": {}}')
            for path, data in ((stock / self.source['source'], self.data),
                               (port / 'vendor/bin/rmt_storage', b'incompatible port daemon'),
                               (port / 'vendor/bin/tftp_server', fixture_elf),
                               (official / crypto_name, fixture_elf)):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            real_info = import_vendor.elf_info
            for soname in real_info(stock / self.source['source'])['needed']:
                if not import_vendor.platform_library(soname):
                    (port / 'vendor/lib64' / soname).write_bytes(fixture_elf)
            def info(path):
                if path.name == 'rmt_storage':
                    self.assertEqual(path, stock / self.source['source'])
                    return real_info(path)
                return {'elf_class': 64, 'machine': 'EM_AARCH64', 'needed': []}
            with patch.object(import_vendor, 'ROOT', root), \
                 patch.object(import_vendor, 'official_crypto_root', return_value=official), \
                 patch.object(import_vendor, 'graphics_inputs', return_value={}), \
                 patch.object(import_vendor, 'elf_info', side_effect=info), \
                 patch.object(import_vendor.subprocess, 'check_output', return_value=fixture_elf):
                import_vendor.import_vendor(port, official, gpu, stock)
            self.assertEqual((root / 'proprietary' / self.name).read_bytes(), self.data)
            self.assertEqual(verify_rmt_storage.verify_tree(root), self.source)
            self.assertIn(self.source['source_dump'] + '@supplied-dump/vendor/bin/rmt_storage:',
                          (root / 'proprietary-files.txt').read_text())


if __name__ == '__main__':
    unittest.main()
