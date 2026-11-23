"""Content-addressed multi-document library with a persistent vector cache.

Each document is named by the SHA-256 of its exact bytes, never a filename. The
on-disk cache is only a cache: it is trusted when it reproduces the freshly
parsed chunks and the current model exactly, otherwise the document is
re-embedded. Cache files contain extracted text, so keep the store directory as
private as the documents themselves. Local trusted inputs; not a server.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .answer import (DEFAULT_MIN_SCORE, Citation, build_answer,
                     check_min_score)
from .pdf import Chunk, DocumentError, read_pdf, chunk_pages
from .search import Index, LocalEmbedder, MODEL, unit

CACHE_VERSION = 1
MAX_TOTAL_CHUNKS = 5000
MAX_CACHE_FILE_BYTES = 50 * 1024 * 1024
HASH_RE = re.compile(r'[0-9a-f]{64}')


class CacheMiss(Exception):
    """Persisted vectors could not be trusted; recompute them."""


def check_hash(value):
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ValueError('document id must be a lowercase SHA-256 hex digest')
    return value


class Library:
    def __init__(self, store_dir, embedder=None, cache_dir=None, offline=False, ocr=False):
        self.ocr = ocr
        self.store = Path(store_dir)
        self._embedder = embedder
        self.cache_dir = cache_dir
        self.offline = offline

    def embedder(self):
        if self._embedder is None:
            self._embedder = LocalEmbedder(self.cache_dir, self.offline)
        return self._embedder

    def _path(self, sha):
        return self.store / (check_hash(sha) + '.json')

    def _read_cache(self, path):
        """Validated cache payload, or CacheMiss. Never trust blindly."""
        try:
            if path.stat().st_size > MAX_CACHE_FILE_BYTES:
                raise CacheMiss('cache file exceeds the size cap')
            payload = json.loads(path.read_text())
        except CacheMiss:
            raise
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            raise CacheMiss('cache unreadable')
        if not isinstance(payload, dict) or payload.get('version') != CACHE_VERSION:
            raise CacheMiss('unsupported cache version')
        if payload.get('model') != MODEL:
            raise CacheMiss('cache was embedded with a different model')
        sha = path.stem
        if not HASH_RE.fullmatch(sha) or payload.get('source_sha256') != sha:
            raise CacheMiss('cache id mismatch')
        raw = payload.get('chunks')
        if not isinstance(raw, list):
            raise CacheMiss('cache chunks malformed')
        chunks, vectors = [], []
        for entry in raw:
            if not isinstance(entry, dict):
                raise CacheMiss('cache chunk entry malformed')
            page, start, end = entry.get('page'), entry.get('start'), entry.get('end')
            text, vector = entry.get('text'), entry.get('vector')
            if (type(page) is not int or type(start) is not int
                    or type(end) is not int or not isinstance(text, str)
                    or not isinstance(vector, list)
                    or page < 1 or start < 0 or end < start):
                raise CacheMiss('cache chunk fields invalid')
            try:
                vectors.append(unit(vector))
            except (ValueError, TypeError):
                raise CacheMiss('cache vector invalid')
            chunks.append(Chunk(page, start, end, text, sha))
        meta = {'version': CACHE_VERSION, 'model': MODEL, 'source_sha256': sha,
                'pages': payload.get('pages'),
                'no_text_pages': payload.get('no_text_pages') or [],
                'ocr_pages': payload.get('ocr_pages') or [],
                'extraction': payload.get('extraction', 'text')}
        return {'meta': meta, 'chunks': chunks, 'vectors': vectors}

    def _cached_chunk_total(self):
        total = 0
        if self.store.is_dir():
            for path in self.store.glob('*.json'):
                if not HASH_RE.fullmatch(path.stem):
                    continue
                try:
                    total += len(self._read_cache(path)['chunks'])
                except CacheMiss:
                    continue  # corrupt entries get repaired on their next add
        return total

    def add_bytes(self, data):
        """Add one PDF's bytes; embed only when the cache cannot be trusted."""
        if len(data) > 20 * 1024 * 1024:
            raise DocumentError('PDF exceeds the input size limit')
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory(prefix='docchat-lib-') as tmp:
            snapshot = Path(tmp) / 'source.pdf'
            snapshot.write_bytes(data)
            pages = read_pdf(snapshot)
            ocr_pages = []
            if self.ocr:
                from .ocr import fill_textless_pages
                pages, ocr_pages = fill_textless_pages(snapshot, pages)
        chunks = chunk_pages(pages, size=500, overlap=75, source=digest)
        meta = {'version': CACHE_VERSION, 'model': MODEL, 'source_sha256': digest,
                'pages': len(pages),
                'extraction': 'tesseract-eng-v1' if self.ocr else 'text',
                'ocr_pages': ocr_pages,
                'no_text_pages': [p.page for p in pages if p.status == 'no_text']}
        old_count = 0
        try:
            old_count = len(self._read_cache(self._path(digest))['chunks'])
        except CacheMiss:
            pass
        if self._cached_chunk_total() - old_count + len(chunks) > MAX_TOTAL_CHUNKS:
            raise DocumentError('library exceeds the total chunk limit')
        try:
            cache = self._read_cache(self._path(digest))
            cached = cache['chunks']
            if (cache['meta']['extraction'] == meta['extraction']
                    and [(c.page, c.start, c.end, c.text) for c in cached] ==
                    [(c.page, c.start, c.end, c.text) for c in chunks]):
                return dict(meta, chunks=len(chunks), embedded=False)
        except (CacheMiss, OSError):
            pass
        vectors = []
        if chunks:
            raw = self.embedder().embed([c.text for c in chunks])
            if len(raw) != len(chunks):
                raise RuntimeError('embedding count does not match chunks')
            vectors = [list(unit(v)) for v in raw]
            Index(chunks, vectors=vectors)
        self.store.mkdir(parents=True, exist_ok=True)
        payload = dict(meta, chunks=[{'page': c.page, 'start': c.start,
                                      'end': c.end, 'text': c.text, 'vector': v}
                                     for c, v in zip(chunks, vectors)])
        target = self._path(digest)
        fd, tmpname = tempfile.mkstemp(dir=str(self.store), prefix='.tmp-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(payload, stream)
            os.replace(tmpname, target)
        except BaseException:
            try:
                os.unlink(tmpname)
            except OSError:
                pass
            raise
        return dict(meta, chunks=len(chunks), embedded=True)

    def documents(self):
        if not self.store.is_dir():
            return []
        result = []
        for path in sorted(self.store.glob('*.json')):
            if not HASH_RE.fullmatch(path.stem):
                raise DocumentError(f'unexpected cache filename: {path.name}')
            try:
                data = self._read_cache(path)
            except CacheMiss as exc:
                raise DocumentError(f'corrupt cache file {path.name}: re-add the document ({exc})')
            result.append({'source_sha256': path.stem,
                           'pages': data['meta']['pages'],
                           'chunks': len(data['chunks']),
                           'no_text_pages': data['meta']['no_text_pages'],
                           'ocr_pages': data['meta']['ocr_pages']})
        return result

    def index(self, embedder=None):
        """Merged index from validated cache. An embedder is required only to
        embed new queries, not to load persisted document vectors."""
        if not self.store.is_dir():
            return Index([], None)
        chunks, vectors = [], []
        for path in sorted(self.store.glob('*.json')):
            if not HASH_RE.fullmatch(path.stem):
                raise DocumentError(f'unexpected cache filename: {path.name}')
            try:
                data = self._read_cache(path)
            except CacheMiss as exc:
                raise DocumentError(f'corrupt cache file {path.name}: re-add the document ({exc})')
            chunks.extend(data['chunks'])
            vectors.extend(data['vectors'])
        if len(chunks) > MAX_TOTAL_CHUNKS:
            raise DocumentError('library exceeds the total chunk limit')
        return Index(chunks, embedder, vectors=vectors)

    @staticmethod
    def _bound(citation, matches):
        """A citation must quote a retrieved match AND its owning document."""
        return any(citation.page == m.page and citation.start == m.start
                   and citation.end == m.end and citation.text == m.text
                   and citation.score == m.score
                   and m.source == citation.source_sha256 for m in matches)

    def ask(self, question, min_score=DEFAULT_MIN_SCORE, k=3):
        threshold = check_min_score(min_score)
        index = self.index()
        if index.chunks:
            index.embedder = self.embedder()
        matches = index.search(question, k)
        answer = build_answer(question, matches, '', threshold)
        for citation in answer['citations']:
            if not self._bound(Citation(**citation), matches):
                raise RuntimeError('internal citation failed validation')
        return {'documents': len(self.documents()), 'chunks': len(index.chunks),
                **answer}

    def remove(self, sha):
        path = self._path(sha)  # validates before any filesystem use
        if path.exists():
            path.unlink()
            return True
        return False


def main():
    parser = argparse.ArgumentParser(description='Content-addressed local PDF library with cited answers. Trusted local inputs only.')
    sub = parser.add_subparsers(dest='command', required=True)
    p_add = sub.add_parser('add', help='Add PDFs to the library')
    p_add.add_argument('store')
    p_add.add_argument('pdfs', nargs='+')
    p_add.add_argument('--cache-dir')
    p_add.add_argument('--offline', action='store_true')
    p_add.add_argument('--ocr', action='store_true', help='OCR textless pages using local Tesseract English')
    p_list = sub.add_parser('list', help='List documents')
    p_list.add_argument('store')
    p_ask = sub.add_parser('ask', help='Ask across the whole library')
    p_ask.add_argument('store')
    p_ask.add_argument('question')
    p_ask.add_argument('--k', type=int, default=3)
    p_ask.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE)
    p_ask.add_argument('--cache-dir')
    p_ask.add_argument('--offline', action='store_true')
    p_rm = sub.add_parser('remove', help='Remove a document by its SHA-256')
    p_rm.add_argument('store')
    p_rm.add_argument('sha256')
    args = parser.parse_args()
    try:
        if args.command == 'add':
            lib = Library(args.store, cache_dir=args.cache_dir, offline=args.offline, ocr=args.ocr)
            added = []
            for name in args.pdfs:
                with open(name, 'rb') as stream:
                    data = stream.read(20 * 1024 * 1024 + 1)
                added.append(dict(file=name, **lib.add_bytes(data)))
            out = {'added': added}
        elif args.command == 'list':
            out = {'documents': Library(args.store).documents()}
        elif args.command == 'ask':
            if not 1 <= args.k <= 20:
                parser.error('k must be between 1 and 20')
            lib = Library(args.store, cache_dir=args.cache_dir, offline=args.offline)
            out = lib.ask(args.question, args.min_score, args.k)
        else:
            out = {'removed': Library(args.store).remove(args.sha256)}
    except (DocumentError, OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'Library failed ({type(exc).__name__}); check inputs, store and model cache. No partial results produced.', file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
