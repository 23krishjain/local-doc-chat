import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from docchat.pdf import DocumentError
from docchat.render import render_pages
from pdf_fixtures import make_pdf


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source, self.output = self.root / 'sample.pdf', self.root / 'rendered'
        make_pdf(self.source, ['Physical page one', None, 'Physical page three'])

    def test_selected_physical_page_and_manifest(self):
        manifest = render_pages(self.source, self.output, pages=[3], dpi=72)
        self.assertEqual(manifest['source_pages'], 3)
        self.assertEqual(manifest['source_sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(manifest['pages'][0]['page'], 3)
        self.assertEqual(manifest['pages'][0]['file'], 'page-0003.png')
        self.assertEqual(json.loads((self.output / 'manifest.json').read_text()), manifest)
        self.assertEqual(sorted(p.name for p in self.output.iterdir()), ['manifest.json', 'page-0003.png'])
        with Image.open(self.output / 'page-0003.png') as im:
            self.assertEqual(im.size, (400, 400))
            self.assertLess(im.convert('L').getextrema()[0], 100)  # text actually rendered

    def test_blank_page_remains_white_no_text(self):
        manifest = render_pages(self.source, self.output, pages=[2], dpi=72)
        self.assertEqual(manifest['pages'][0]['text_status'], 'no_text')
        with Image.open(self.output / 'page-0002.png') as im:
            self.assertEqual(im.convert('L').getextrema(), (255, 255))

    def test_default_renders_all_pages(self):
        self.assertEqual([p['page'] for p in render_pages(self.source, self.output)['pages']], [1, 2, 3])

    def test_existing_directory_untouched(self):
        self.output.mkdir(); marker = self.output / 'keep'; marker.write_text('keep')
        with self.assertRaises(DocumentError):
            render_pages(self.source, self.output)
        self.assertEqual(marker.read_text(), 'keep')

    def test_pixel_budget_checked_before_render(self):
        with patch('pypdfium2.PdfPage.render') as render:
            with self.assertRaisesRegex(DocumentError, 'pixel budget'):
                render_pages(self.source, self.output, max_pixels=1)
            render.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.docchat-*')))

    def test_total_budget_failure_removes_partial_work(self):
        with self.assertRaisesRegex(DocumentError, 'pixel budget'):
            render_pages(self.source, self.output, dpi=72, max_total_pixels=200000)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.docchat-*')))

    def test_invalid_pages(self):
        for pages in [[], [0], [4], [1, 1], [True], [1.5]]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                render_pages(self.source, self.output, pages=pages)
        self.assertFalse(self.output.exists())

    def test_invalid_dpi(self):
        for dpi in [0, 201, float('inf'), float('nan')]:
            with self.subTest(dpi=dpi), self.assertRaises(ValueError):
                render_pages(self.source, self.output, dpi=dpi)

    def test_byte_budget(self):
        with self.assertRaises(DocumentError):
            render_pages(self.source, self.output, max_bytes=1)

    def test_corrupt_file(self):
        self.source.write_bytes(b'%PDF-broken')
        with self.assertRaises(DocumentError):
            render_pages(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_encrypted_file(self):
        make_pdf(self.source, ['secret sample'], password='fixture')
        with self.assertRaisesRegex(DocumentError, 'encrypted'):
            render_pages(self.source, self.output)

    def test_renderer_failure_cleans_staging(self):
        with patch('pypdfium2.PdfPage.render', side_effect=OSError('fixture failure')):
            with self.assertRaises(DocumentError):
                render_pages(self.source, self.output)
        self.assertFalse(self.output.exists())
        self.assertFalse(list(self.root.glob('.docchat-*')))

    def test_image_only_sample_renders_without_claiming_text(self):
        source = Path(__file__).resolve().parents[1] / 'samples' / 'scanned-receipt.pdf'
        manifest = render_pages(source, self.output, dpi=72)
        self.assertEqual(manifest['pages'][0]['text_status'], 'no_text')
        with Image.open(self.output / 'page-0001.png') as im:
            self.assertEqual(im.size, (648, 432))
            self.assertLess(im.convert('L').getextrema()[0], 100)
