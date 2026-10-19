#!/usr/bin/env python3
"""Store and restore a verified builder without duplicate expanded image layers."""
import argparse
from decimal import Decimal
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile

PART_BYTES = 4 * 1024**3
PART_LIMIT = 16


class ChunkWriter:
    def __init__(self, directory, limit):
        self.directory, self.limit = directory, limit
        self.file, self.size, self.chunks = None, 0, []

    def write(self, data):
        total = len(data)
        while data:
            if self.file is None:
                if len(self.chunks) >= PART_LIMIT:
                    raise ValueError('Prepared snapshot exceeds bounded layer capacity')
                self.name = f'part{len(self.chunks):02d}'
                self.file = (self.directory / self.name).open('wb')
                self.digest, self.size = hashlib.sha256(), 0
            piece = data[:self.limit - self.size]
            self.file.write(piece)
            self.digest.update(piece)
            self.size += len(piece)
            data = data[len(piece):]
            if self.size == self.limit:
                self.finish_chunk()
        return total

    def finish_chunk(self):
        if self.file is not None:
            self.file.close()
            self.chunks.append({'name': self.name, 'bytes': self.size,
                                'sha256': self.digest.hexdigest()})
            self.file = None

    def flush(self):
        if self.file is not None:
            self.file.flush()


def pack(source, directory, part_bytes=PART_BYTES, remove_source=False):
    source, directory = Path(source), Path(directory)
    if not source.is_dir() or not 0 < part_bytes <= PART_BYTES:
        raise ValueError('Invalid snapshot source or layer size')
    if directory.resolve().is_relative_to(source.resolve()):
        raise ValueError('Snapshot output must be outside its source')
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError('Snapshot output must be empty')
    if remove_source and source.is_symlink():
        raise ValueError('Cannot release a symlinked source root')
    writer = ChunkWriter(directory, part_bytes)

    class ReleasingTar(tarfile.TarFile):
        def addfile(self, member, fileobj=None):
            super().addfile(member, fileobj)
            if member.isfile() or member.issym() or member.islnk():
                original = source.joinpath(*PurePosixPath(member.name).parts[1:])
                if not original.parent.resolve().is_relative_to(source.resolve()):
                    raise ValueError('Cannot release a path outside the source root')
                original.unlink()

        def add(self, name, arcname=None, recursive=True, *, filter=None):
            super().add(name, arcname, recursive, filter=filter)
            original = Path(name)
            if original.is_dir() and not original.is_symlink():
                # The known skipped Ninja FIFO can keep a directory nonempty.
                try:
                    original.rmdir()
                except OSError:
                    pass

    def metadata(member):
        # Ninja recreates this IPC endpoint. It contains no sources or cache.
        if member.name == 'aera/out/.ninja_fifo' and member.isfifo():
            return None
        original = source.joinpath(*PurePosixPath(member.name).parts[1:])
        ns = original.stat(follow_symlinks=False).st_mtime_ns
        # Float timestamps lose nanoseconds and invalidate Ninja's saved cache.
        member.pax_headers['mtime'] = str(Decimal(ns) / Decimal(10**9))
        member.uid = member.gid = 0
        member.uname = member.gname = 'root'
        return member

    with gzip.GzipFile(filename='', fileobj=writer, mode='wb',
                       compresslevel=1, mtime=0) as compressed:
        archive_type = ReleasingTar if remove_source else tarfile.TarFile
        with archive_type.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
            archive.add(source, arcname='aera', filter=metadata)
    writer.finish_chunk()
    result = {'schema': 1, 'root': 'aera', 'format': 'tar+gzip',
              'archive_bytes': sum(c['bytes'] for c in writer.chunks),
              'chunks': writer.chunks}
    (directory / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    # Fixed COPY instructions keep every image layer below registry limits.
    for index in range(len(writer.chunks), PART_LIMIT):
        (directory / f'part{index:02d}').touch()
    print(f'Prepared snapshot: {result["archive_bytes"]} bytes in {len(writer.chunks)} bounded layers')
    return result


def verified_parts(directory):
    directory = Path(directory)
    record = json.loads((directory / 'manifest.json').read_text())
    if record.get('schema') != 1 or record.get('root') != 'aera' or record.get('format') != 'tar+gzip':
        raise ValueError('Unsupported prepared snapshot')
    chunks = record['chunks']
    if not 0 < len(chunks) <= PART_LIMIT:
        raise ValueError('Invalid snapshot chunk count')
    parts = []
    for index, chunk in enumerate(chunks):
        if chunk['name'] != f'part{index:02d}' or not 0 < chunk['bytes'] <= PART_BYTES:
            raise ValueError('Invalid snapshot chunk name or size')
        if not re.fullmatch('[0-9a-f]{64}', chunk['sha256']):
            raise ValueError('Invalid snapshot checksum')
        path = directory / chunk['name']
        if path.is_symlink() or path.stat().st_size != chunk['bytes']:
            raise ValueError(f'Changed snapshot chunk: {path.name}')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for data in iter(lambda: stream.read(1024**2), b''):
                digest.update(data)
        if digest.hexdigest() != chunk['sha256']:
            raise ValueError(f'Snapshot checksum mismatch: {path.name}')
        parts.append(path)
    if record['archive_bytes'] != sum(c['bytes'] for c in chunks):
        raise ValueError('Invalid snapshot total size')
    return parts


class PartsReader(io.RawIOBase):
    def __init__(self, parts):
        self.parts = iter(parts)
        self.file = None

    def readable(self):
        return True

    def read(self, size):
        result = []
        while size:
            if self.file is None:
                path = next(self.parts, None)
                if path is None:
                    break
                self.file = path.open('rb')
            data = self.file.read(size)
            if not data:
                self.file.close()
                self.file = None
                continue
            result.append(data)
            size -= len(data)
        return b''.join(result)

    def close(self):
        if self.file is not None:
            self.file.close()
        super().close()


def mtime_ns(member):
    return int(Decimal(member.pax_headers.get('mtime', str(member.mtime))) * Decimal(10**9))


class PreciseTar(tarfile.TarFile):
    def utime(self, member, path):
        ns = mtime_ns(member)
        os.utime(path, ns=(ns, ns))


def restore(directory, parent):
    parts = verified_parts(directory)
    parent = Path(parent).resolve()
    target = parent / 'aera'
    if target.exists() or target.is_symlink():
        raise ValueError('Restore destination already exists')
    links = []
    seen = set()

    def safe_name(name):
        path = PurePosixPath(name)
        return not path.is_absolute() and '..' not in path.parts and path.parts[:1] == ('aera',)

    def members(archive):
        for member in archive:
            if not safe_name(member.name):
                raise ValueError(f'Unsafe snapshot member: {member.name}')
            name = PurePosixPath(member.name)
            if name in seen:
                raise ValueError(f'Duplicate snapshot member: {member.name}')
            seen.add(name)
            path = parent / member.name
            if path == target:
                if not member.isdir():
                    raise ValueError('Snapshot root must be a directory')
            elif not path.parent.resolve().is_relative_to(target):
                raise ValueError(f'Snapshot traverses a symlink: {member.name}')
            # Already-published snapshots contain the same transient pipe.
            # Skip that exact path; never restore IPC nodes or device files.
            if member.name == 'aera/out/.ninja_fifo' and member.isfifo():
                print('Skipped transient Ninja FIFO; the builder recreates it')
                continue
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError(f'Unsafe snapshot member: {member.name}')
            if member.islnk() and (not safe_name(member.linkname) or
                                  not (parent / member.linkname).resolve().is_relative_to(target)):
                raise ValueError(f'Unsafe snapshot hardlink: {member.linkname}')
            if member.issym():
                links.append((path, mtime_ns(member)))
            yield member

    with PartsReader(parts) as stream:
        with PreciseTar.open(fileobj=stream, mode='r|gz') as archive:
            # Own validation applies consistently to Ubuntu 22.04 and newer Python.
            options = {'filter': 'fully_trusted'} if hasattr(tarfile, 'data_filter') else {}
            archive.extractall(parent, members=members(archive), **options)
    for path, ns in links:
        os.utime(path, ns=(ns, ns), follow_symlinks=False)
    (Path(directory) / 'restored').write_text('Verified prepared snapshot restored\n')
    print('Restored verified prepared sources, toolchains, host tools and build graph')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('pack', 'restore'))
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    parser.add_argument('--remove-source', action='store_true',
                        help='Release the disposable /aera checkout while packing')
    args = parser.parse_args()
    if args.remove_source and (args.mode != 'pack' or args.first.resolve() != Path('/aera')):
        parser.error('--remove-source is restricted to packing the disposable /aera checkout')
    if args.mode == 'pack':
        pack(args.first, args.second, remove_source=args.remove_source)
    else:
        restore(args.first, args.second)
