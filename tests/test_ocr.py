import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docchat.ocr import fill_textless_pages, tesseract_text
from docchat.pdf import PageText, DocumentError, read_pdf
from docchat.library import Library

ROOT = Path(__file__).resolve().parents[1]


class OCRTests(unittest.TestCase):
    def test_text_pages_are_untouched(self):
        pages = [PageText(1, 'already extracted', 'text')]
        result, attempted = fill_textless_pages('unused', pages)
        self.assertEqual(result, pages)
        self.assertEqual(attempted, [])

    def test_too_many_pages_fail_before_render(self):
        with self.assertRaises(DocumentError):
            fill_textless_pages('unused', [PageText(i, '', 'no_text') for i in range(1, 12)])

    def test_ocr_preserves_page_and_marks_empty(self):
        source = ROOT / 'samples/scanned-receipt.pdf'
        pages = read_pdf(source)
        result, attempted = fill_textless_pages(source, pages, runner=lambda p: '')
        self.assertEqual(attempted, [1])
        self.assertEqual(result, [PageText(1, '', 'no_text')])

    def test_ocr_returns_text(self):
        source = ROOT / 'samples/scanned-receipt.pdf'
        result, _ = fill_textless_pages(source, read_pdf(source), runner=lambda p: 'INR 180')
        self.assertEqual(result, [PageText(1, 'INR 180', 'text')])

    def test_missing_executable_actionable(self):
        with patch('docchat.ocr.subprocess.run', side_effect=FileNotFoundError):
            with self.assertRaisesRegex(DocumentError, 'install Tesseract'):
                tesseract_text('x.png')

    def test_timeout_becomes_document_error(self):
        with patch('docchat.ocr.subprocess.run', side_effect=subprocess.TimeoutExpired('tesseract', 1)):
            with self.assertRaisesRegex(DocumentError, 'timed out'):
                tesseract_text('x.png')

    @unittest.skipUnless(shutil.which('tesseract'), 'Tesseract not installed')
    def test_actual_english_receipt_ocr(self):
        source = ROOT / 'samples/scanned-receipt.pdf'
        result, attempted = fill_textless_pages(source, read_pdf(source))
        self.assertEqual(attempted, [1])
        self.assertIn('TOTAL: INR 180', result[0].text)

    def test_empty_library_does_not_load_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Library(tmp)
            with patch.object(lib, 'embedder', side_effect=AssertionError('no model needed')):
                self.assertEqual(lib.ask('anything')['status'], 'insufficient_evidence')

    def test_ocr_failure_does_not_write_partial_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            lib = Library(tmp, ocr=True)
            with patch('docchat.ocr.fill_textless_pages', side_effect=DocumentError('timeout')):
                with self.assertRaises(DocumentError):
                    lib.add_bytes((ROOT / 'samples/scanned-receipt.pdf').read_bytes())
            self.assertEqual(list(Path(tmp).glob('*.json')), [])

    def test_addition_of_ocr_mode_repairs_previous_empty_cache(self):
        class Embedder:
            def embed(self, texts):
                return [[1., 0.] for _ in texts]
        with tempfile.TemporaryDirectory() as tmp:
            data = (ROOT / 'samples/scanned-receipt.pdf').read_bytes()
            self.assertEqual(Library(tmp).add_bytes(data)['chunks'], 0)
            with patch('docchat.ocr.fill_textless_pages', return_value=([PageText(1, 'TOTAL INR 180', 'text')], [1])):
                lib = Library(tmp, embedder=Embedder(), ocr=True)
                self.assertTrue(lib.add_bytes(data)['embedded'])
                self.assertEqual(lib.documents()[0]['ocr_pages'], [1])
                answer = lib.ask('total?')
                self.assertEqual(answer['citations'][0]['page'], 1)
