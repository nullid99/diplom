import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from backend.app.config import PROJECT_ROOT
from scripts.audit_dfire import inspect_image


class DFireAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit-test-', dir=PROJECT_ROOT / '.tmp')
        self.root = Path(self.temp.name)
        (self.root / 'train/images').mkdir(parents=True)
        (self.root / 'train/labels').mkdir()
        self.image = self.root / 'train/images/synthetic.png'
        Image.new('RGB', (100, 100), 'orange').save(self.image)
        self.label = self.root / 'train/labels/synthetic.txt'

    def tearDown(self):
        self.temp.cleanup()

    def inspect(self):
        with patch('scripts.audit_dfire.DATASET', self.root):
            return inspect_image(('train', self.image))

    def test_missing_label_is_not_background(self):
        record = self.inspect()
        self.assertFalse(record['background_verified'])
        self.assertIn('missing_label_unknown_background', record['issues'])

    def test_explicit_empty_label(self):
        self.label.write_text('', encoding='utf-8')
        record = self.inspect()
        self.assertTrue(record['background_verified'])
        self.assertFalse(record['issues'])

    def test_valid_classes_and_source_unchanged(self):
        text = '0 0.5 0.5 0.2 0.2\n1 0.5 0.5 1 1\n'
        self.label.write_text(text, encoding='utf-8')
        record = self.inspect()
        self.assertFalse(record['issues'])
        self.assertEqual([box[0] for box in record['boxes']], [0, 1])
        self.assertEqual(self.label.read_text(encoding='utf-8'), text)

    def test_invalid_boxes_and_class(self):
        for text in ('2 0.5 0.5 0.1 0.1', '0 nan 0.5 0.1 0.1', '0 0.1 0.1 0.9 0.9', '1 0.5 0.5 0 0.2'):
            with self.subTest(text=text):
                self.label.write_text(text, encoding='utf-8')
                self.assertTrue(self.inspect()['issues'])


if __name__ == '__main__':
    unittest.main()
