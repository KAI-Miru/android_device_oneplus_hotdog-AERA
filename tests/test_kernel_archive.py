import gzip
import hashlib
import io
import struct
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci'))
from select_kernel_input import select_image


class KernelArchiveTests(unittest.TestCase):
    def fixture(self):
        image = bytes(56)+b'ARMd'+bytes(4)+b'Linux version 4.14.test\0'
        return image, hashlib.sha256(image).hexdigest()

    def archive(self, entries):
        output = io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            for name, data in entries:
                entry = zipfile.ZipInfo()
                entry.filename = name  # Preserve unsafe names even on Windows.
                archive.writestr(entry,data)
        return output.getvalue()

    def recovery_container(self, image):
        header = bytearray(4096)
        header[:8] = b'ANDROID!'
        for offset, value in ((8, len(image)), (36, 4096), (40, 2), (1644, 1660)):
            struct.pack_into('<I', header, offset, value)
        return bytes(header) + image + b'not imported ramdisk/DTB/DTBO'

    def test_retained_recovery_selects_only_the_exact_approved_kernel(self):
        image, digest = self.fixture()
        recovery = self.recovery_container(image)
        self.assertEqual(select_image(recovery, digest), image)
        archive = self.archive([('AERA-hotdog-ALPHA-recovery.img', recovery),
                                ('SHA256SUMS', b'container checksum')])
        self.assertEqual(select_image(archive, digest), image)
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            select_image(recovery, '0' * 64)

    def test_recovery_rejects_bad_framing_bounds_and_ambiguous_members(self):
        image, digest = self.fixture()
        recovery = self.recovery_container(image)
        for offset, value in ((36, 2048), (40, 3), (1644, 0),
                              (8, 0), (8, 0xffffffff)):
            bad = bytearray(recovery)
            struct.pack_into('<I', bad, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                select_image(bytes(bad), digest)
        for entries in ([('../AERA-hotdog-ALPHA-recovery.img', recovery)],
                        [('metadata.txt', b'no kernel here')],
                        [('Image', image), ('AERA-hotdog-ALPHA-recovery.img', recovery)],
                        [('AERA-hotdog-ALPHA-recovery.img', recovery)] * 2):
            with self.subTest(names=[n for n, _ in entries]), self.assertRaises(ValueError):
                select_image(self.archive(entries), digest)

    def test_raw_and_compressed_images_are_verified(self):
        image, digest = self.fixture()
        self.assertEqual(select_image(image,digest),image)
        self.assertEqual(select_image(gzip.compress(image)+b'unused DTB',digest),image)
        with self.assertRaisesRegex(ValueError,'SHA256'):
            select_image(image,'0'*64)

    def test_flash_archive_selects_only_the_image_without_extracting_files(self):
        image, digest = self.fixture()
        archive = self.archive([('arch/arm64/boot/Image.gz-dtb',gzip.compress(image)+b'DTB'),
                                ('production-device-trees/dtb.img',b'not selected'),
                                ('docs/outside',b'never extracted')])
        self.assertEqual(select_image(archive,digest),image)

    def test_arbitrary_wrapper_and_kernel_names_are_selected_by_content(self):
        image, digest = self.fixture()
        for name in ('ColorOS15-ci59-flash-files.zip', 'ColorOS17-universal-ci14-flash-files.zip',
                     'future-release.bundle', 'artifacts/renamed-input.bin'):
            flash = self.archive([('new-layout/kernel.payload', gzip.compress(image)+b'DTB'),
                                  ('device-tree.img', b'not a kernel')])
            wrapper = self.archive([(name, flash), ('checksums.txt', b'checksum')])
            with self.subTest(name=name):
                self.assertEqual(select_image(wrapper, digest), image)
        for name in ('AERA-guacamole-ALPHA-boot.img', 'recovery.img', 'custom/build-output.dat'):
            self.assertEqual(select_image(self.archive([(name, self.recovery_container(image))]), digest), image)

    def test_wrappers_reject_traversal_extra_nesting_and_multiple_inputs(self):
        image, digest = self.fixture()
        flash = self.archive([('kernel', image)])
        wrapper = self.archive([('bundle.zip', flash)])
        payloads = [self.archive([('../bundle.zip',flash)]),
                    self.archive([('bundle.zip',wrapper)]),
                    self.archive([('a.zip',flash),('b.zip',flash)]),
                    self.archive([('kernel',image),('bundle.zip',flash)]),
                    self.archive([('/kernel',image)]),
                    self.archive([('folder\\kernel',image)]),
                    self.archive([('C:kernel',image)]),
                    self.archive([('kernel',image),('../notes',b'not extracted')])]
        for payload in payloads:
            with self.subTest(prefix=payload[:6]), self.assertRaises(ValueError):
                select_image(payload,digest)

    def test_hash_is_required_after_renamed_wrapper_selection(self):
        image, digest = self.fixture()
        wrapper = self.archive([('any-name.zip', self.archive([('anything.img',image)]))])
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            select_image(wrapper, '0'*64)

    def test_archive_member_count_and_uncompressed_size_are_bounded(self):
        from unittest.mock import patch
        import select_kernel_input as selector
        image, digest = self.fixture()
        payload = self.archive([('kernel', image), ('notes', b'notes')])
        with patch.object(selector, 'MAX_ARCHIVE_MEMBERS', 1), self.assertRaises(ValueError):
            select_image(payload,digest)
        # A compressed member must be bounded before archive.read materializes it.
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('kernel', image + bytes(10000))
        with patch.object(selector, 'MAX_IMAGE_BYTES', 1000), self.assertRaises(ValueError):
            select_image(output.getvalue(),digest)

    def test_duplicate_and_symlink_archive_members_are_rejected(self):
        image, digest = self.fixture()
        duplicate = self.archive([('kernel',image),('kernel',image)])
        with self.assertRaises(ValueError):
            select_image(duplicate,digest)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as z:
            entry=zipfile.ZipInfo('kernel')
            entry.create_system=3
            entry.external_attr=0o120777 << 16
            z.writestr(entry,image)
        with self.assertRaises(ValueError):
            select_image(output.getvalue(),digest)

    def test_missing_or_ambiguous_kernel_and_corrupt_gzip_are_rejected(self):
        image, digest = self.fixture()
        for payload in (self.archive([('../Image',image)]),
                        self.archive([('Image',image),('arch/arm64/boot/Image',image)]),
                        gzip.compress(image)[:-4],b'not an Image'):
            with self.subTest(prefix=payload[:6]), self.assertRaises(ValueError):
                select_image(payload,digest)


if __name__ == '__main__':
    unittest.main()
