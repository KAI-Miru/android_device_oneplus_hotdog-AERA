#!/usr/bin/env python3
"""Read an Image or the original CI flash archive without importing its DTBs."""
import argparse
import hashlib
import io
from pathlib import Path
import zipfile
import zlib

MAX_IMAGE_BYTES = 128 * 1024 * 1024
KERNEL_MEMBERS = {'Image', 'arch/arm64/boot/Image', 'arch/arm64/boot/Image.gz-dtb'}


def select_image(payload, expected_sha256):
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            candidates = [entry for entry in archive.infolist() if entry.filename in KERNEL_MEMBERS]
            if len(candidates) != 1 or candidates[0].file_size > MAX_IMAGE_BYTES:
                raise ValueError('Expected one bounded kernel Image in the archive')
            payload = archive.read(candidates[0])
    if payload[:2] == b'\x1f\x8b':
        # Image.gz-dtb is one gzip stream followed by concatenated device trees.
        # Device-specific DTB/DTBO inputs come separately from the device tree.
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decoder.decompress(payload, MAX_IMAGE_BYTES + 1)
        if not decoder.eof or len(payload) > MAX_IMAGE_BYTES:
            raise ValueError('Invalid or oversized compressed kernel Image')
    if len(payload) > MAX_IMAGE_BYTES or len(payload) < 64 or payload[56:60] != b'ARMd':
        raise ValueError('Expected an uncompressed ARM64 Image')
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError('Selected Image SHA256 differs from the approved input')
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('download')
    parser.add_argument('output')
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    Path(args.output).write_bytes(select_image(Path(args.download).read_bytes(), args.sha256))
