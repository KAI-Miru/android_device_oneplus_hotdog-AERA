"""Pin remote storage to the original device-compatible stock implementation."""
import hashlib
import io
import json
import stat
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]


def verify_blob(data, source):
    if len(data) != source['bytes'] or hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('Remote storage differs from the pinned stock rmt_storage')
    elf = ELFFile(io.BytesIO(data))
    if elf.elfclass != 64 or elf.header['e_machine'] != 'EM_AARCH64':
        raise ValueError('Stock rmt_storage must be ARM64')
    dynamic = elf.get_section_by_name('.dynamic')
    needed = [t.needed for t in dynamic.iter_tags() if t.entry.d_tag == 'DT_NEEDED'] if dynamic else []
    return {'elf_class': 64, 'machine': 'EM_AARCH64', 'needed': needed}


def stock_input(dump, source):
    dump = Path(dump)
    if dump.name != source['source_dump']:
        raise ValueError('Remote storage must come from ' + source['source_dump'])
    data = (dump / source['source']).read_bytes()
    verify_blob(data, source)
    return data


def verify_tree(root=ROOT):
    root = Path(root)
    source = json.loads((root / 'tools/rmt-storage-source.json').read_text())
    manifest = json.loads((root / 'proprietary/manifest.json').read_text())
    if manifest.get('rmt_storage_source') != source:
        raise ValueError('Stock rmt_storage source provenance is missing or changed')
    record = manifest['files'][source['destination']]
    for key in ('source_dump', 'source', 'bytes', 'sha256'):
        if record.get(key) != source[key]:
            raise ValueError('Stock rmt_storage provenance differs: ' + key)
    info = verify_blob((root / 'proprietary' / source['destination']).read_bytes(), source)
    if any(record.get(key) != value for key, value in info.items()):
        raise ValueError('Stock rmt_storage ELF metadata differs')
    return source


def verify_runtime(entries):
    source = json.loads((ROOT / 'tools/rmt-storage-source.json').read_text())
    name = source['destination']
    if name not in entries or not stat.S_ISREG(entries[name][0]) or not entries[name][0] & 0o111:
        raise ValueError('Pinned stock rmt_storage must be a regular executable')
    verify_blob(entries[name][1], source)
    return {'source_dump': source['source_dump'], 'sha256': source['sha256'],
            'shared_memory': source['shared_memory'], 'device_tested': False}
