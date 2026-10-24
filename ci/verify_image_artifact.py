"""Require the actual verified image before publishing its checksum archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

IMAGE_BYTES = 96 * 1024 * 1024


def verify(directory):
    directory = Path(directory).resolve()
    rows = (directory / 'SHA256SUMS').read_text().splitlines()
    if len(rows) != 1:
        raise ValueError('Image artifact requires exactly one checksum entry')
    match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', rows[0])
    if not match:
        raise ValueError('Malformed image checksum entry')
    digest, name = match.groups()
    if Path(name).name != name or any(c in name for c in ('/', '\\', ':', '\n', '\r')) or not name.endswith('.img'):
        raise ValueError('Image checksum must name a local image file')
    image = directory / name
    if image.is_symlink() or not image.is_file():
        raise ValueError('Required image is missing; refusing checksum-only upload')
    if set(directory.glob('*.img')) != {image}:
        raise ValueError('Image artifact directory contains unexpected images')
    if image.stat().st_size != IMAGE_BYTES:
        raise ValueError('Image artifact must be the physical 96 MiB image')
    actual = hashlib.sha256()
    with image.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            actual.update(chunk)
    report = json.loads((directory / 'image-verification.json').read_text())
    if actual.hexdigest() != digest or report.get('sha256') != digest or report.get('image_bytes') != IMAGE_BYTES:
        raise ValueError('Image, checksum and verification report disagree')
    return image


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    image = verify(args.directory)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('image_path=' + str(image) + '\n')
    print('Verified required image artifact: ' + image.name)
