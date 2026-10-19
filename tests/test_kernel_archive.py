import gzip
import hashlib
import io
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
                archive.writestr(name,data)
        return output.getvalue()

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
                                ('../outside',b'never extracted')])
        self.assertEqual(select_image(archive,digest),image)

    def test_github_artifact_wrapper_selects_the_named_flash_archive(self):
        image, digest = self.fixture()
        flash = self.archive([('arch/arm64/boot/Image.gz-dtb',gzip.compress(image)+b'DTB')])
        wrapper = self.archive([('ColorOS15-ci59-flash-files.zip',flash),
                                ('ColorOS15-ci59-flash-files.sha256',b'checksum')])
        self.assertEqual(select_image(wrapper,digest),image)
        for payload in (self.archive([('other.zip',flash)]),
                        self.archive([('../ColorOS15-ci59-flash-files.zip',flash)]),
                        self.archive([('ColorOS15-ci59-flash-files.zip',wrapper)])):
            with self.subTest(prefix=payload[:6]), self.assertRaises(ValueError):
                select_image(payload,digest)

    def test_missing_or_ambiguous_kernel_and_corrupt_gzip_are_rejected(self):
        image, digest = self.fixture()
        for payload in (self.archive([('../Image',image)]),
                        self.archive([('Image',image),('arch/arm64/boot/Image',image)]),
                        gzip.compress(image)[:-4],b'not an Image'):
            with self.subTest(prefix=payload[:6]), self.assertRaises(ValueError):
                select_image(payload,digest)


if __name__ == '__main__':
    unittest.main()
