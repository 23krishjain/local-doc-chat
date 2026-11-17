"""Render selected local PDF pages to PNG with provenance. No OCR/model calls."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile

import pypdfium2 as pdfium

from .pdf import DocumentError, read_pdf


def render_pages(source, output, *, pages=None, dpi=120, max_pixels=4_000_000,
                 max_total_pixels=20_000_000, max_bytes=20 * 1024 * 1024):
    """Create a NEW directory with page PNGs and manifest.json.

    Page numbers are physical and 1-based. Rendering is explicitly selected,
    not inferred from no_text: a blank page is not necessarily a scan.
    Pixel checks bound bitmap size, not native-parser memory/CPU consumption.
    Only trusted local files are supported. No hostile-input isolation yet.
    """
    if not math.isfinite(dpi) or not 36 <= dpi <= 200:
        raise ValueError('dpi must be finite and between 36 and 200')
    if min(max_pixels, max_total_pixels, max_bytes) <= 0:
        raise ValueError('limits must be positive')
    source, output = Path(source), Path(output)
    if output.exists():
        raise DocumentError('output already exists; choose a new directory')
    if not output.parent.is_dir():
        raise DocumentError('output parent directory does not exist')
    try:
        with source.open('rb') as stream:
            data = stream.read(max_bytes + 1)
    except OSError as exc:
        raise DocumentError('could not read local PDF') from exc
    if len(data) > max_bytes:
        raise DocumentError('PDF exceeds the input size limit')
    # Parse a stable snapshot, not a path that could change between passes.
    staging = Path(tempfile.mkdtemp(prefix='.docchat-', dir=output.parent))
    document = None
    try:
        snapshot = staging / 'input.pdf'
        snapshot.write_bytes(data)
        extracted = read_pdf(snapshot, max_bytes=max_bytes)
        selected = list(range(1, len(extracted) + 1)) if pages is None else list(pages)
        if (not selected or len(set(selected)) != len(selected)
                or any(type(n) is not int or n < 1 or n > len(extracted) for n in selected)):
            raise ValueError('pages must be unique physical page numbers within this PDF')
        document = pdfium.PdfDocument(data)
        records, total = [], 0
        scale = dpi / 72
        for number in selected:
            page = document[number - 1]
            bitmap = None
            try:
                width, height = page.get_size()
                if not all(math.isfinite(n) and n > 0 for n in (width, height)):
                    raise DocumentError('invalid PDF page dimensions')
                pixels = math.ceil(width * scale) * math.ceil(height * scale)
                total += pixels
                if pixels > max_pixels or total > max_total_pixels:
                    raise DocumentError('render exceeds the pixel budget; lower dpi or select fewer pages')
                bitmap = page.render(scale=scale)
                image = bitmap.to_pil()
                filename = f'page-{number:04d}.png'
                try:
                    image.save(staging / filename)
                    actual_width, actual_height = image.size
                finally:
                    image.close()
                records.append({'page': number, 'file': filename,
                                'width': actual_width, 'height': actual_height,
                                'text_status': extracted[number - 1].status})
            finally:
                if bitmap is not None:
                    bitmap.close()
                page.close()
        manifest = {'source_sha256': hashlib.sha256(data).hexdigest(),
                    'source_pages': len(extracted), 'dpi': dpi, 'pages': records,
                    'warning': 'Rendered pixels only; no OCR, model reading or answer verification performed.'}
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        snapshot.unlink()  # Never retain an extra copy of the original PDF.
        # output is user-selected and must not exist. Staging is cleaned on failure.
        if output.exists():
            raise DocumentError('output appeared during processing; refusing to replace it')
        staging.rename(output)
        return manifest
    except (pdfium.PdfiumError, OSError) as exc:
        raise DocumentError('PDF rendering failed; check the file and output location') from exc
    finally:
        if document is not None:
            document.close()
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description='Render trusted PDF pages as PNGs. No OCR or model call.')
    parser.add_argument('pdf')
    parser.add_argument('output')
    parser.add_argument('--pages', type=int, nargs='+', help='Physical 1-based pages; default all')
    parser.add_argument('--dpi', type=float, default=120)
    args = parser.parse_args()
    try:
        manifest = render_pages(args.pdf, args.output, pages=args.pages, dpi=args.dpi)
    except (DocumentError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
