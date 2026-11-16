import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject
from docchat.pdf import read_pdf, chunk_pages, PageText, DocumentError
from pdf_fixtures import make_pdf


class PDFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'sample.pdf'

    def test_reads_real_text_pdf_and_physical_pages(self):
        make_pdf(self.path, ['Tea costs INR 80.', 'Total INR 180.'])
        pages = read_pdf(self.path)
        self.assertEqual([p.page for p in pages], [1, 2])
        self.assertIn('Tea costs INR 80.', pages[0].text)
        self.assertIn('Total INR 180.', pages[1].text)
        self.assertTrue(all(p.status == 'text' for p in pages))

    def test_blank_page_retained_without_renumbering(self):
        make_pdf(self.path, ['First', None, 'Third'])
        pages = read_pdf(self.path)
        self.assertEqual(pages[1], PageText(2, '', 'no_text'))
        self.assertEqual([c.page for c in chunk_pages(pages)], [1, 3])

    def test_image_only_page_is_no_text_not_fake_ocr(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=400, height=400)
        image = DecodedStreamObject()
        image.set_data(b'\xff\xff\xff')  # one RGB white pixel
        image.update({NameObject('/Type'): NameObject('/XObject'),
                      NameObject('/Subtype'): NameObject('/Image'),
                      NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                      NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                      NameObject('/BitsPerComponent'): NumberObject(8)})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'): DictionaryObject({NameObject('/Im0'): writer._add_object(image)})})
        contents = DecodedStreamObject()
        contents.set_data(b'q 200 0 0 200 0 0 cm /Im0 Do Q')
        page[NameObject('/Contents')] = writer._add_object(contents)
        writer.write(self.path)
        self.assertEqual(read_pdf(self.path)[0].status, 'no_text')
        self.assertEqual(chunk_pages(read_pdf(self.path)), [])

    def test_encrypted_rejected(self):
        make_pdf(self.path, ['Private sample'], password='test-only')
        with self.assertRaisesRegex(DocumentError, 'encrypted'):
            read_pdf(self.path)

    def test_corrupt_rejected(self):
        self.path.write_bytes(b'%PDF-1.7\nnot a valid PDF')
        with self.assertRaises(DocumentError):
            read_pdf(self.path)

    def test_nonpdf_rejected(self):
        self.path.write_text('plain text, not PDF')
        with self.assertRaisesRegex(DocumentError, 'expected a PDF'):
            read_pdf(self.path)

    def test_missing_rejected(self):
        with self.assertRaisesRegex(DocumentError, 'could not read'):
            read_pdf(self.path)

    def test_page_limit(self):
        make_pdf(self.path, [None, None])
        with self.assertRaisesRegex(DocumentError, 'page limit'):
            read_pdf(self.path, max_pages=1)

    def test_byte_limit(self):
        make_pdf(self.path, ['Text'])
        with self.assertRaisesRegex(DocumentError, 'size limit'):
            read_pdf(self.path, max_bytes=10)

    def test_character_limit(self):
        make_pdf(self.path, ['A' * 100])
        with self.assertRaisesRegex(DocumentError, 'character limit'):
            read_pdf(self.path, max_chars=10)

    def test_no_pages(self):
        PdfWriter().write(self.path)
        with self.assertRaisesRegex(DocumentError, 'no pages'):
            read_pdf(self.path)

    def test_bad_limits(self):
        for kwargs in [{'max_bytes': 0}, {'max_chars': -1}, {'max_pages': 0}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                read_pdf(self.path, **kwargs)

    def test_chunks_preserve_offsets_and_overlap(self):
        pages = [PageText(1, 'abcdefghijk', 'text')]
        chunks = chunk_pages(pages, size=5, overlap=2)
        self.assertEqual([(c.start, c.end, c.text) for c in chunks], [(0, 5, 'abcde'), (3, 8, 'defgh'), (6, 11, 'ghijk')])
        for c in chunks:
            self.assertEqual(c.text, pages[0].text[c.start:c.end])

    def test_exact_chunk_boundary_no_redundant_tail(self):
        chunks = chunk_pages([PageText(3, 'abcdef', 'text')], size=6, overlap=1)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].page, 3)

    def test_whitespace_has_no_chunks(self):
        self.assertEqual(chunk_pages([PageText(1, '  \n ', 'no_text')]), [])

    def test_zero_overlap_covers_all_text(self):
        text = 'hello world'
        self.assertEqual(''.join(c.text for c in chunk_pages([PageText(1, text, 'text')], size=3, overlap=0)), text)

    def test_invalid_chunk_settings(self):
        for size, overlap in [(0, 0), (5, -1), (5, 5), (5, 6)]:
            with self.subTest(size=size, overlap=overlap), self.assertRaises(ValueError):
                chunk_pages([], size=size, overlap=overlap)

    def test_cli_json_and_failure_without_partial_output(self):
        make_pdf(self.path, ['Total INR 180'])
        proc = subprocess.run([sys.executable, '-m', 'docchat.pdf', str(self.path)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['pages'][0]['page'], 1)
        self.path.write_text('broken')
        proc = subprocess.run([sys.executable, '-m', 'docchat.pdf', str(self.path)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, '')
        self.assertIn('expected a PDF', proc.stderr)
