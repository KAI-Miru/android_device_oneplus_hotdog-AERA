#!/usr/bin/env python3
"""Select the approved Image without importing a container's ramdisk or DTBs."""
import argparse
import hashlib
import io
from pathlib import Path
import struct
import zipfile
import zlib

MAX_IMAGE_BYTES = 128 * 1024 * 1024
FLASH_ARCHIVE = 'ColorOS15-ci59-flash-files.zip'
KERNEL_MEMBERS = {'Image', 'arch/arm64/boot/Image', 'arch/arm64/boot/Image.gz-dtb',
                  'AERA-hotdog-ALPHA-recovery.img'}


def select_image(payload, expected_sha256, *, artifact_wrapper=True):
    if zipfile.is_zipfile(io.BytesIO(payload)):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            candidates = [entry for entry in archive.infolist() if entry.filename in KERNEL_MEMBERS]
            if not candidates and artifact_wrapper:
                wrappers = [entry for entry in archive.infolist() if entry.filename == FLASH_ARCHIVE]
                if len(wrappers) == 1 and wrappers[0].file_size <= MAX_IMAGE_BYTES:
                    return select_image(archive.read(wrappers[0]), expected_sha256, artifact_wrapper=False)
            if len(candidates) != 1 or candidates[0].file_size > MAX_IMAGE_BYTES:
                raise ValueError('Expected one bounded kernel Image in the archive')
            payload = archive.read(candidates[0])
    if payload[:8] == b'ANDROID!':
        # A retained, revision-pinned AERA recovery artifact can preserve the
        # same external kernel after its original CI artifact expires. Read
        # only the boot-v2 kernel span; never import its ramdisk, DTB or DTBO.
        if (len(payload) < 1660 or len(payload) > MAX_IMAGE_BYTES or
                struct.unpack_from('<I', payload, 40)[0] != 2 or
                struct.unpack_from('<I', payload, 1644)[0] != 1660 or
                struct.unpack_from('<I', payload, 36)[0] != 4096):
            raise ValueError('Expected a bounded boot-v2 kernel container')
        size = struct.unpack_from('<I', payload, 8)[0]
        if size < 64 or 4096 + size > len(payload):
            raise ValueError('Invalid boot-v2 kernel bounds')
        payload = payload[4096:4096 + size]
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
