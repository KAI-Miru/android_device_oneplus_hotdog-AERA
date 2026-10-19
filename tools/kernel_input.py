"""Check a caller-supplied ARM64 Image and its compatibility with the WLAN module."""
import argparse
import hashlib
import json
from pathlib import Path
import re

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
    parser.add_argument('image')
    parser.add_argument('--sha256')
    parser.add_argument('--module-manifest')
    parser.add_argument('--report')
    args = parser.parse_args()
    module = None
    if args.module_manifest:
        module = json.loads(Path(args.module_manifest).read_text())['files']['qca_cld3_wlan.ko']
    record = inspect_kernel(args.image, args.sha256, module)
    if args.report:
        Path(args.report).write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
