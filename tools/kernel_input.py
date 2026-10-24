"""Verify the versioned original F.22 boot blobs and matching WLAN module."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = ('boot-header-v2.bin', 'kernel', 'ramdisk-stock.cpio.gz',
              'recovery-dtbo.img', 'dtb.img')


def verify_bundled_boot(root=ROOT):
    root = Path(root)
    manifest = json.loads((root / 'prebuilt/manifest.json').read_text())
    if set(manifest['files']) != set(COMPONENTS) or manifest['source_ramdisk_imported']:
        raise ValueError('Expected original boot components and a native AERA ramdisk')
    blobs = {}
    for name in COMPONENTS:
        data = (root / 'prebuilt' / name).read_bytes()
        record = manifest['files'][name]
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError(f'Bundled F22 boot component identity differs: {name}')
        blobs[name] = data
    header = blobs['boot-header-v2.bin']
    if (len(header) != 4096 or header[:8] != b'ANDROID!' or
            struct.unpack_from('<I', header, 36)[0] != 4096 or
            struct.unpack_from('<I', header, 40)[0] != 2):
        raise ValueError('Invalid original F22 boot header')
    digest, size = hashlib.sha256(header), len(header)
    for name in COMPONENTS[1:]:
        data = blobs[name]
        padding = bytes((-len(data)) % 4096)
        digest.update(data); digest.update(padding)
        size += len(data) + len(padding)
    if size != manifest['stock_boot_payload_bytes'] or digest.hexdigest() != manifest['stock_boot_payload_sha256']:
        raise ValueError('Original F22 boot payload does not reconstruct exactly')
    kernel = blobs['kernel']
    start = kernel.find(b'IKCFG_ST'); end = kernel.find(b'IKCFG_ED', start)
    if start < 0 or end < 0 or b'CONFIG_RD_LZMA=y\n' not in gzip.decompress(kernel[start + 8:end]):
        raise ValueError('Bundled kernel must support the native legacy LZMA ramdisk')
    modules = json.loads((root / 'modules/manifest.json').read_text())
    record = modules['files']['qca_cld3_wlan.ko']
    module = (root / 'modules/qca_cld3_wlan.ko').read_bytes()
    if len(module) != record['bytes'] or hashlib.sha256(module).hexdigest() != record['sha256']:
        raise ValueError('Bundled WLAN module identity differs')
    if modules['matching_boot_sha256'] != manifest['source_sha256']:
        raise ValueError('WLAN module and original boot provenance differ')
    return inspect_kernel(root / 'prebuilt/kernel', manifest['files']['kernel']['sha256'], record)

def inspect_kernel(path, expected_sha256=None, module_record=None):
    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('Supplied Image SHA256 does not match the requested input')
    if len(data) < 64 or data[56:60] != b'ARMd':
        raise ValueError('Supply an uncompressed ARM64 Image with a valid Image header')
    banner = re.search(rb'Linux version ([^\s\x00]+)', data)
    release = banner.group(1).decode('ascii') if banner else None
    if module_record is not None:
        required = module_record['vermagic'].split()[0]
        if release != required:
            raise ValueError(f'Supplied Image release {release!r} does not match the WLAN module ({required})')
    return {'bytes': len(data), 'sha256': digest, 'release': release}

def verify_image_kernel(data, path, module_record=None):
    record = inspect_kernel(path, module_record=module_record)
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('Boot image does not contain the supplied Image')
    return record

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report')
    args = parser.parse_args()
    record = verify_bundled_boot()
    if args.report:
        target = Path(args.report); target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
