"""Evidence-gated, cited answers. Extractive quotes only, no generated text."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

from .pdf import DocumentError, read_pdf, chunk_pages
from .search import Index, LocalEmbedder, Match, MODEL

# Separates the included 8-question, two-page synthetic fixture only. Cosine
# scores are not probabilities; retune per corpus and model before relying on it.
DEFAULT_MIN_SCORE = 0.34


@dataclass(frozen=True)
class Citation:
    page: int
    start: int
    end: int
    text: str
    score: float
    source_sha256: str


def check_min_score(min_score):
    if isinstance(min_score, bool) or not isinstance(min_score, (int, float)):
        raise ValueError('min_score must be a number from 0 to 1')
    if not math.isfinite(min_score) or not 0 <= float(min_score) <= 1:
        raise ValueError('min_score must be a finite number from 0 to 1')
    return float(min_score)


def citation_for(match, source_sha256):
    if not isinstance(match, Match):
        raise ValueError('citation source must be a retrieved Match')
    # Multi-document matches carry their own document hash; single-document
    # callers pass it explicitly. Never invent a source.
    source = match.source if getattr(match, 'source', '') else source_sha256
    return Citation(match.page, match.start, match.end, match.text,
                    match.score, source)


def is_valid_citation(citation, matches, source_sha256):
    """Valid only if the citation quotes a retrieved match exactly, byte-bound."""
    if not isinstance(citation, Citation) or citation.source_sha256 != source_sha256:
        return False
    return any(citation.page == m.page and citation.start == m.start
               and citation.end == m.end and citation.text == m.text
               and citation.score == m.score for m in matches)


def build_answer(question, matches, source_sha256, min_score=DEFAULT_MIN_SCORE):
    """Answer from retrieved evidence or abstain. Never invents text: the
    excerpt is always the exact retrieved passage."""
    threshold = check_min_score(min_score)
    if not question.strip():
        raise ValueError('question must not be blank')
    matches = list(matches)
    if not matches or matches[0].score < threshold:
        return {'status': 'insufficient_evidence', 'question': question,
                'citations': [],
                'nearest_evidence': [{**asdict(m), 'below_threshold': True}
                                     for m in matches],
                'min_score': threshold}
    supporting = [m for m in matches if m.score >= threshold]
    citations = [citation_for(m, source_sha256) for m in supporting]
    return {'status': 'answered', 'question': question,
            'excerpt': citations[0].text,
            'citations': [asdict(c) for c in citations],
            'min_score': threshold}


def answer_bytes(data, question, *, min_score=DEFAULT_MIN_SCORE, k=3,
                 cache_dir=None, offline=False):
    """Run the cited-answer pipeline over bounded PDF bytes already in memory.
    Shared by the CLI and the loopback web UI."""
    threshold = check_min_score(min_score)
    if not question.strip():
        raise ValueError('question must not be blank')
    if type(k) is not int or not 1 <= k <= 20:
        raise ValueError('k must be an integer from 1 to 20')
    if len(data) > 20 * 1024 * 1024:
        raise DocumentError('PDF exceeds the input size limit')
    # Hash and parse the same bounded bytes, not a path that may change.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='docchat-answer-') as tmp:
        snapshot = Path(tmp) / 'source.pdf'
        snapshot.write_bytes(data)
        pages = read_pdf(snapshot)
    chunks = chunk_pages(pages, size=500, overlap=75)
    if len(chunks) > 2000:
        raise DocumentError('too many chunks for this small in-memory index')
    embedder = LocalEmbedder(cache_dir, offline) if chunks else None
    matches = Index(chunks, embedder).search(question, k)
    digest = hashlib.sha256(data).hexdigest()
    answer = build_answer(question, matches, digest, threshold)
    for citation in answer['citations']:
        if not is_valid_citation(Citation(**citation), matches, digest):
            raise RuntimeError('internal citation failed validation')
    return {'source_sha256': digest, 'model': MODEL, 'chunks': len(chunks),
            **answer,
            'no_text_pages': [p.page for p in pages if p.status == 'no_text'],
            'warning': 'Extractive passage quotes with provenance, not a generated answer. The abstention threshold is fixture-tuned, not calibrated confidence.'}


def main():
    parser = argparse.ArgumentParser(description='Answer from PDF evidence with page citations, or abstain when evidence is weak. Extractive only; no generative model is used.')
    parser.add_argument('pdf')
    parser.add_argument('question')
    parser.add_argument('--k', type=int, default=3)
    parser.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument('--cache-dir')
    parser.add_argument('--offline', action='store_true', help='Use downloaded model files only')
    args = parser.parse_args()
    if not args.question.strip() or not 1 <= args.k <= 20:
        parser.error('provide a nonblank question and k between 1 and 20')
    try:
        source = Path(args.pdf)
        with source.open('rb') as stream:
            data = stream.read(20 * 1024 * 1024 + 1)
        result = answer_bytes(data, args.question, min_score=args.min_score,
                              k=args.k, cache_dir=args.cache_dir,
                              offline=args.offline)
    except (DocumentError, OSError, ValueError, RuntimeError, ImportError) as exc:
        print(f'Answer failed ({type(exc).__name__}); check the PDF, dependencies and model cache. No partial results produced.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
