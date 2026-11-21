"""Extract page-linked text. No OCR, model calls, or uploads."""
import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class DocumentError(Exception):
    """An input could not be processed within this reader's limits."""


@dataclass(frozen=True)
class PageText:
    page: int  # physical, 1-based PDF page, not a printed page label
    text: str
    status: str  # text, or no_text (blank, scan, or otherwise unextractable)


@dataclass(frozen=True)
class Chunk:
    page: int
    start: int  # character offset in extracted page text, inclusive
    end: int  # exclusive
    text: str
    source: str = ''  # SHA-256 of the owning document's bytes, when known


def read_pdf(path, *, max_bytes=20 * 1024 * 1024, max_pages=100,
             max_chars=1_000_000):
    """Return every physical page, including pages with no extractable text.

    These limits are guardrails, NOT a hostile-PDF sandbox. Parsing/decompression
    can consume memory before a page/character limit can be checked.
    """
    if min(max_bytes, max_pages, max_chars) <= 0:
        raise ValueError('document limits must be positive')
    path = Path(path)
    try:
        # Read at most one byte beyond the limit, even if the file grows.
        with path.open('rb') as source:
            data = source.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise DocumentError('PDF exceeds the input size limit')
        if not data.startswith(b'%PDF-'):
            raise DocumentError('expected a PDF file')
        from io import BytesIO
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise DocumentError('encrypted PDFs are not supported; use a decrypted local copy')
        if len(reader.pages) > max_pages:
            raise DocumentError('PDF exceeds the page limit')
        if not reader.pages:
            raise DocumentError('PDF has no pages')
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ''
            total += len(text)
            if total > max_chars:
                raise DocumentError('PDF exceeds the extracted character limit')
            status = 'text' if text.strip() else 'no_text'
            pages.append(PageText(number, text, status))
        return pages
    except DocumentError:
        raise
    except OSError as exc:
        raise DocumentError('could not read the local PDF file') from exc
    except (PyPdfError, ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        raise DocumentError('PDF could not be parsed; it may be damaged or unsupported') from exc


def chunk_pages(pages, *, size=1000, overlap=150, source=''):
    """Fixed character chunks, never crossing a physical page.

    Offsets refer to the exact extracted text. Character counts are not tokens.
    Fixed splitting can cut words; retrieval quality must be evaluated later.
    """
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError('require size > 0 and 0 <= overlap < size')
    chunks = []
    for page in pages:
        if page.status != 'text':
            continue
        start = 0
        while start < len(page.text):
            end = min(start + size, len(page.text))
            text = page.text[start:end]
            if text.strip():
                chunks.append(Chunk(page.page, start, end, text, source))
            if end == len(page.text):
                break
            start = end - overlap
    return chunks


def main():
    parser = argparse.ArgumentParser(description='Extract local PDF text and page-linked chunks (no OCR).')
    parser.add_argument('pdf')
    parser.add_argument('--chunk-size', type=int, default=1000)
    parser.add_argument('--overlap', type=int, default=150)
    args = parser.parse_args()
    try:
        # Validate chunk settings before opening a file.
        chunk_pages([], size=args.chunk_size, overlap=args.overlap)
        pages = read_pdf(args.pdf)
        result = {'pages': [asdict(p) for p in pages],
                  'chunks': [asdict(c) for c in chunk_pages(pages, size=args.chunk_size, overlap=args.overlap)]}
    except (DocumentError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
