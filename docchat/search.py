"""Small in-memory dense-vector retrieval. Returns evidence, not answers."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

from .pdf import DocumentError, read_pdf, chunk_pages

MODEL = 'sentence-transformers/all-MiniLM-L6-v2'


@dataclass(frozen=True)
class Match:
    page: int
    start: int
    end: int
    text: str
    score: float  # cosine similarity, NOT a probability or confidence
    source: str = ''  # owning document hash, when the chunk carries one


def unit(vector):
    values = [float(x) for x in vector]
    if not values or not all(math.isfinite(x) for x in values):
        raise ValueError('embedding must be a nonempty finite vector')
    norm = math.sqrt(sum(x*x for x in values))
    if not math.isfinite(norm) or norm == 0:
        raise ValueError('embedding must have a finite nonzero norm')
    return tuple(x / norm for x in values)


class LocalEmbedder:
    """Explicit first-use model download; later use can be cache-only.

    FastEmbed runs the ONNX text model on CPU, not the vision model. Hugging
    Face receives model download requests, not the document text. No hosted
    inference API, API key or paid service is used.
    """
    model_name = MODEL

    def __init__(self, cache_dir=None, offline=False):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(MODEL, cache_dir=cache_dir, threads=2,
                                   local_files_only=offline)
        # Clone the pinned backend tokenizer to count before its 256-token
        # truncation. Do not change the tokenizer used by model inference.
        from tokenizers import Tokenizer
        self.counter = Tokenizer.from_str(self.model.model.tokenizer.to_str())
        self.counter.no_truncation()
        self.counter.no_padding()

    def embed(self, texts):
        texts = list(texts)
        if any(len(self.counter.encode(text).ids) > 256 for text in texts):
            raise ValueError("embedding input exceeds 256 tokens; use smaller chunks or query")
        return list(self.model.embed(texts, batch_size=8))


class Index:
    def __init__(self, chunks, embedder=None, vectors=None):
        self.chunks = tuple(chunks)
        self.embedder = embedder
        if vectors is None:
            if self.chunks and embedder is None:
                raise ValueError('an embedder or precomputed vectors are required')
            vectors = embedder.embed([c.text for c in self.chunks]) if self.chunks else []
        if len(vectors) != len(self.chunks):
            raise ValueError('embedding count does not match chunks')
        self.vectors = tuple(unit(v) for v in vectors)
        self.dimension = len(self.vectors[0]) if self.vectors else None
        if any(len(v) != self.dimension for v in self.vectors):
            raise ValueError('embedding dimensions must match')

    def search(self, question, k=3):
        if not question.strip():
            raise ValueError('question must not be blank')
        if type(k) is not int or not 1 <= k <= 20:
            raise ValueError('k must be an integer from 1 to 20')
        if not self.vectors:
            return []
        query_vectors = self.embedder.embed([question])
        if len(query_vectors) != 1:
            raise ValueError('expected exactly one query embedding')
        query = unit(query_vectors[0])
        if len(query) != self.dimension:
            raise ValueError('query embedding dimension does not match index')
        ranked = sorted(enumerate(self.vectors),
                        key=lambda pair: (-sum(a*b for a, b in zip(query, pair[1])), pair[0]))
        result = []
        for i, v in ranked[:k]:
            c = self.chunks[i]
            result.append(Match(c.page, c.start, c.end, c.text,
                                max(-1.0, min(1.0, sum(a*b for a,b in zip(query,v)))),
                                getattr(c, 'source', '')))
        return result


def main():
    parser = argparse.ArgumentParser(description='Find PDF evidence using a local CPU embedding model. Does not answer questions.')
    parser.add_argument('pdf')
    parser.add_argument('question')
    parser.add_argument('--k', type=int, default=3)
    parser.add_argument('--cache-dir')
    parser.add_argument('--offline', action='store_true', help='Use downloaded model files only')
    args = parser.parse_args()
    if not args.question.strip() or not 1 <= args.k <= 20:
        parser.error('provide a nonblank question and k between 1 and 20')
    try:
        # Hash and parse the same bounded bytes, not a path that may change.
        source = Path(args.pdf)
        with source.open('rb') as stream:
            data = stream.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise DocumentError('PDF exceeds the input size limit')
        import tempfile
        with tempfile.TemporaryDirectory(prefix='docchat-search-') as tmp:
            snapshot = Path(tmp) / 'source.pdf'; snapshot.write_bytes(data)
            pages = read_pdf(snapshot)
        digest = hashlib.sha256(data).hexdigest()
        chunks = chunk_pages(pages, size=500, overlap=75, source=digest)
        if len(chunks) > 2000:
            raise DocumentError('too many chunks for this small in-memory index')
        embedder = LocalEmbedder(args.cache_dir, args.offline) if chunks else None
        matches = Index(chunks, embedder).search(args.question, args.k)
        result = {'source_sha256': digest, 'model': MODEL,
                  'chunks': len(chunks), 'matches': [asdict(m) for m in matches],
                  'no_text_pages': [p.page for p in pages if p.status == 'no_text'],
                  'warning': 'Nearest evidence only. Scores are not confidence. Results can be irrelevant when the answer is absent.'}
    except (DocumentError, OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'Search failed ({type(exc).__name__}); check the PDF, dependencies and model cache. No partial results produced.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
