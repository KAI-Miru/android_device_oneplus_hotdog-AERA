import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from prepared_snapshot import PART_LIMIT, pack, restore


class PreparedSnapshotTests(unittest.TestCase):
    def test_ninja_fifo_is_omitted_from_new_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'source/out').mkdir(parents=True)
            os.mkfifo(base / 'source/out/.ninja_fifo')
            (base / 'source/out/build.ninja').write_text('build rules')
            pack(base / 'source', base / 'snapshot')
            (base / 'destination').mkdir()
            restore(base / 'snapshot', base / 'destination')
            self.assertFalse((base / 'destination/aera/out/.ninja_fifo').exists())
            self.assertEqual((base / 'destination/aera/out/build.ninja').read_text(), 'build rules')

    def test_legacy_ninja_fifo_is_skipped_but_other_special_nodes_are_rejected(self):
        for name, kind in (('aera/out/.ninja_fifo', tarfile.FIFOTYPE),
                           ('aera/other_pipe', tarfile.FIFOTYPE),
                           ('aera/out/.ninja_fifo', tarfile.CHRTYPE)):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w') as archive:
                    for parent in ('aera', 'aera/out'):
                        member = tarfile.TarInfo(parent)
                        member.type = tarfile.DIRTYPE
                        member.mode = 0o755
                        archive.addfile(member)
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    archive.addfile(member)
                data = gzip.compress(stream.getvalue())
                snapshot = base / 'snapshot'
                snapshot.mkdir()
                (snapshot / 'part00').write_bytes(data)
                (snapshot / 'manifest.json').write_text(json.dumps({
                    'schema': 1, 'root': 'aera', 'format': 'tar+gzip',
                    'archive_bytes': len(data), 'chunks': [{'name': 'part00',
                        'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}]}))
                (base / 'destination').mkdir()
                if name == 'aera/out/.ninja_fifo' and kind == tarfile.FIFOTYPE:
                    restore(snapshot, base / 'destination')
                    self.assertTrue((snapshot / 'restored').exists())
                else:
                    with self.assertRaises(ValueError):
                        restore(snapshot, base / 'destination')
                    self.assertFalse((snapshot / 'restored').exists())
                self.assertFalse((base / 'destination' / name).exists())

    def test_multiple_chunks_preserve_tools_links_modes_and_ninja_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source'
            (source / 'out/host/bin').mkdir(parents=True)
            tool = source / 'out/host/bin/tool'
            tool.write_bytes(os.urandom(48 * 1024))
            tool.chmod(0o751)
            os.link(tool, source / 'out/host/bin/hardlink')
            (source / 'out/host/bin/link').symlink_to('tool')
            (source / '.aera-prepared-environment.json').write_text('{"fingerprint":"fixture"}')
            timestamp = 1700000000123456789
            for path in [source, *source.rglob('*')]:
                os.utime(path, ns=(timestamp, timestamp), follow_symlinks=False)
            snapshot = base / 'snapshot'
            record = pack(source, snapshot, part_bytes=4096)
            self.assertGreater(len(record['chunks']), 1)
            self.assertTrue(all(c['bytes'] <= 4096 for c in record['chunks']))
            destination = base / 'restored'
            destination.mkdir()
            restore(snapshot, destination)
            target = destination / 'aera'
            for original in [source, *source.rglob('*')]:
                copy = target / original.relative_to(source)
                self.assertEqual(stat.S_IMODE(copy.lstat().st_mode), stat.S_IMODE(original.lstat().st_mode))
                self.assertEqual(copy.lstat().st_mtime_ns, original.lstat().st_mtime_ns)
                if original.is_symlink():
                    self.assertEqual(os.readlink(copy), os.readlink(original))
                elif original.is_file():
                    self.assertEqual(copy.read_bytes(), original.read_bytes())
            self.assertEqual((target / 'out/host/bin/tool').stat().st_ino,
                             (target / 'out/host/bin/hardlink').stat().st_ino)
            self.assertTrue((snapshot / 'restored').is_file())

    def test_corrupt_chunk_is_rejected_before_extracting_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source'
            source.mkdir()
            (source / 'tool').write_bytes(b'compiled tool')
            snapshot = base / 'snapshot'
            pack(source, snapshot)
            part = snapshot / 'part00'
            data = bytearray(part.read_bytes())
            data[len(data) // 2] ^= 1
            part.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                restore(snapshot, base / 'destination')
            self.assertFalse((base / 'destination/aera').exists())
            self.assertFalse((snapshot / 'restored').exists())

    def unsafe_snapshot(self, directory, entries):
        directory.mkdir()
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            root = tarfile.TarInfo('aera')
            root.type = tarfile.DIRTYPE
            archive.addfile(root)
            for name, link in entries:
                member = tarfile.TarInfo(name)
                if link is not None:
                    member.type = tarfile.SYMTYPE
                    member.linkname = link
                    archive.addfile(member)
                else:
                    member.size = 4
                    archive.addfile(member, io.BytesIO(b'data'))
        data = gzip.compress(stream.getvalue())
        (directory / 'part00').write_bytes(data)
        record = {'schema': 1, 'root': 'aera', 'format': 'tar+gzip', 'archive_bytes': len(data),
                  'chunks': [{'name': 'part00', 'bytes': len(data),
                              'sha256': hashlib.sha256(data).hexdigest()}]}
        (directory / 'manifest.json').write_text(json.dumps(record))

    def test_restore_rejects_traversal_and_writes_through_external_symlinks(self):
        cases = [[('aera/../escaped', None)],
                 [('aera/link', '../../outside'), ('aera/link/file', None)],
                 [('aera/link', '../../outside'), ('aera/link', None)]]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                snapshot = base / 'snapshot'
                self.unsafe_snapshot(snapshot, entries)
                destination = base / 'destination'
                destination.mkdir()
                with self.assertRaises(ValueError):
                    restore(snapshot, destination)
                self.assertFalse((base / 'outside').exists())
                self.assertFalse((destination / 'escaped').exists())
                self.assertFalse((snapshot / 'restored').exists())

    def test_missing_chunk_does_not_mark_snapshot_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / 'source'
            source.mkdir()
            (source / 'tool').write_bytes(os.urandom(48 * 1024))
            snapshot = base / 'snapshot'
            record = pack(source, snapshot, part_bytes=4096)
            (snapshot / record['chunks'][-1]['name']).unlink()
            with self.assertRaises(FileNotFoundError):
                restore(snapshot, base / 'destination')
            self.assertFalse((snapshot / 'restored').exists())


if __name__ == '__main__':
    unittest.main()
