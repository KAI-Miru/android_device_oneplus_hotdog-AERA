import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_manifest import write_manifest


class ManifestTests(unittest.TestCase):
    def test_public_https_remotes_keep_exact_source_pins(self):
        lock = json.loads((ROOT / 'sources.lock.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / 'local_manifests' / 'pins.xml'
            write_manifest(destination)
            manifest = ET.parse(destination).getroot()
        remotes = {r.attrib['name']: r.attrib['fetch'] for r in manifest.findall('remote')}
        overrides = {p.attrib['path']: p.attrib for p in manifest.findall('extend-project')}
        self.assertEqual(set(overrides), {p['path'] for p in lock['projects']})
        for project in lock['projects']:
            override = overrides[project['path']]
            self.assertEqual(override['revision'], project['commit'])
            self.assertEqual(override['name'], project['name'])
            if project['remote'] == 'AERA':
                self.assertEqual(remotes[override['remote']], 'https://github.com/AERA-Recovery')
            elif project['remote'] == 'Miru':
                self.assertEqual(remotes[override['remote']], 'https://github.com/KAI-Miru')
            else:
                self.assertNotIn('remote', override)


if __name__ == '__main__':
    unittest.main()
