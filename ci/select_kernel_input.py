#!/usr/bin/env python3
"""Select the approved Image without importing a container's ramdisk or DTBs."""
import argparse
import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import struct
import zipfile
import zlib

MAX_IMAGE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 1024


def payload_kind(prefix):
    if prefix.startswith((b'PK\x03\x04', b'PK\x05\x06')):
        return 'archive'
    if (prefix.startswith((b'ANDROID!', b'\x1f\x8b')) or
            len(prefix) >= 64 and prefix[56:60] == b'ARMd'):
        return 'kernel'
    return None


def archive_payload(payload, artifact_wrapper):
    """Inspect bounded headers in memory; never extract or trust member names."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_MEMBERS:
            raise ValueError('Too many archive members')
        seen, candidates = set(), []
        for entry in entries:
            # ZipInfo can normalize backslashes on Windows. Validate the
            # original spelling as well as collisions in the normalized name.
            original = entry.orig_filename
            path = PurePosixPath(original)
            if (not original or path.is_absolute() or
                    any(part in ('', '.', '..') for part in original.rstrip('/').split('/')) or
                    '\\' in original or ':' in original or '\0' in original or
                    stat.S_ISLNK(entry.external_attr >> 16) or entry.filename in seen):
                raise ValueError('Unsafe or duplicate archive member')
            seen.add(entry.filename)
            if entry.is_dir():
                continue
            with archive.open(entry) as stream:
                kind = payload_kind(stream.read(64))
            if kind:
                if entry.file_size > MAX_IMAGE_BYTES:
                    raise ValueError('Oversized kernel/archive member')
                candidates.append((entry, kind))
        # The hash must not resolve ambiguity between multiple inputs.
        if len(candidates) != 1:
            raise ValueError('Expected one bounded kernel payload or archive wrapper')
        entry, kind = candidates[0]
        if kind == 'archive' and not artifact_wrapper:
            raise ValueError('Extra archive nesting is not supported')
        return archive.read(entry), kind


def select_image(payload, expected_sha256, *, artifact_wrapper=True):
    if len(payload) > MAX_IMAGE_BYTES:
        raise ValueError('Oversized kernel input container')
    if zipfile.is_zipfile(io.BytesIO(payload)):
        try:
            payload, kind = archive_payload(payload, artifact_wrapper)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
            raise ValueError('Unreadable kernel archive') from error
        if kind == 'archive':
            return select_image(payload, expected_sha256, artifact_wrapper=False)
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
