"""Opt-in local OCR for textless PDF pages. Printed English only by default.

Requires a separately installed Tesseract executable + English language data.
PDF parsing/rendering is NOT sandboxed. Only use trusted documents.
"""
from pathlib import Path
import subprocess
import tempfile

from .pdf import DocumentError, PageText


def tesseract_text(image, *, timeout=30, max_chars=100_000):
    """Run an argv-only subprocess, with bounded file output and a timeout."""
    with tempfile.TemporaryDirectory(prefix='docchat-ocr-text-') as tmp:
        base = Path(tmp) / 'result'
        try:
            subprocess.run(['tesseract', str(image), str(base), '-l', 'eng',
                            '--psm', '6'], check=True, timeout=timeout,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            path = base.with_suffix('.txt')
            if path.stat().st_size > max_chars * 4:
                raise DocumentError('OCR text exceeds the output limit')
            text = path.read_text(encoding='utf-8').replace('\f', '').strip() + '\n'
        except FileNotFoundError as exc:
            raise DocumentError('install Tesseract with English language data to use OCR') from exc
        except (subprocess.SubprocessError, OSError, UnicodeError) as exc:
            raise DocumentError('OCR failed or timed out') from exc
        if len(text) > max_chars:
            raise DocumentError('OCR text exceeds the character limit')
        return text


def fill_textless_pages(source, pages, *, runner=tesseract_text, max_pages=10):
    """Preserve physical page numbers. OCR only pages without extracted text.

    Returns (PageText list, OCR-attempted page numbers). OCR text is fallible,
    not a verified transcription. Empty OCR remains no_text. A maximum of ten
    pages per document bounds the default work; failures never save a cache.
    """
    selected = [p.page for p in pages if p.status == 'no_text']
    if len(selected) > max_pages:
        raise DocumentError('OCR exceeds the ten-page limit; split the PDF')
    if not selected:
        return pages, []
    from .render import render_pages
    with tempfile.TemporaryDirectory(prefix='docchat-ocr-') as tmp:
        output = Path(tmp) / 'pages'
        manifest = render_pages(source, output, pages=selected, dpi=150,
                                max_total_pixels=40_000_000)
        text_by_page = {p['page']: runner(output / p['file'])
                        for p in manifest['pages']}
    result = [PageText(p.page, text_by_page[p.page],
                       'text' if text_by_page[p.page].strip() else 'no_text')
              if p.page in text_by_page else p for p in pages]
    if sum(len(p.text) for p in result) > 1_000_000:
        raise DocumentError('PDF exceeds the combined character limit')
    return result, selected
