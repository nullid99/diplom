import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.app.config import PROJECT_ROOT
from scripts.train_technical import readonly_check_image


class ReadOnlyTrainingVerificationTests(unittest.TestCase):
    def test_png_with_exif_and_jpg_extension_is_not_falsely_rejected(self):
        with tempfile.TemporaryDirectory(prefix='png-readonly-',dir=PROJECT_ROOT/'.tmp') as directory:
            image=Path(directory)/'image.jpg'
            exif=Image.Exif()
            exif[274]=1
            Image.new('RGB',(160,120),'orange').save(image,format='PNG',exif=exif)
            before=image.read_bytes()
            self.assertEqual(readonly_check_image(str(image)),('',(120,160)))
            self.assertEqual(image.read_bytes(),before)

    def test_ultralytics_verifier_preserves_decodable_jpeg_with_trailer(self):
        import ultralytics.data.utils as data_utils
        with tempfile.TemporaryDirectory(prefix='jpeg-readonly-',dir=PROJECT_ROOT/'.tmp') as directory:
            image=Path(directory)/'synthetic.jpg'
            label=Path(directory)/'synthetic.txt'
            Image.new('RGB',(160,120),'orange').save(image)
            with image.open('ab') as stream:
                stream.write(b'extra-trailer-data!')
            label.write_text('1 0.5 0.5 0.5 0.5\n',encoding='utf-8')
            before=hashlib.sha256(image.read_bytes()).hexdigest()
            with patch.object(data_utils,'check_image',readonly_check_image):
                result=data_utils.verify_image_label((str(image),str(label),'',False,2,0,0,False))
            self.assertEqual(result[0],str(image))
            self.assertEqual(result[2],(120,160))
            self.assertEqual(result[8],0)
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)

    def test_unreadable_file_is_rejected_without_rewrite(self):
        with tempfile.TemporaryDirectory(prefix='jpeg-invalid-',dir=PROJECT_ROOT/'.tmp') as directory:
            image=Path(directory)/'invalid.jpg'
            image.write_bytes(b'not-an-image')
            with self.assertRaises(Exception):
                readonly_check_image(str(image))
            self.assertEqual(image.read_bytes(),b'not-an-image')


if __name__ == '__main__':
    unittest.main()
