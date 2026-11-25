"""Retrieval comparison on a small real corpus: dense vs BM25 vs hybrid (RRF).

Corpus: four public arXiv papers, downloaded by this script. Relevance rule: a
retrieved chunk is relevant if its whitespace-normalised text contains the
question's evidence string. Questions were written by the repo author, so this
is a small, author-labelled set, not a general benchmark.
Run: python eval/hybrid_eval.py --download /tmp/corpus [--cache-dir D]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docchat.hybrid import HybridRanker
from docchat.pdf import chunk_pages, read_pdf
from docchat.search import LocalEmbedder, unit

root = Path(__file__).resolve().parents[1]
CHUNK = 300
ARXIV = ['1706.03762', '1810.04805', '2005.11401', '2210.03629']
norm = lambda s: re.sub(r'\s+', ' ', s)


def mean(xs):
    return sum(xs) / len(xs)


def metrics(order, relevant, ks=(1, 3, 5, 10)):
    first = next((r for r, i in enumerate(order, 1) if i in relevant), None)
    out = {'rr': 1 / first if first else 0.0}
    for k in ks:
        out['recall@%d' % k] = 1.0 if first and first <= k else 0.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--download', required=True)
    ap.add_argument('--cache-dir')
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    folder = Path(a.download)
    folder.mkdir(parents=True, exist_ok=True)
    hashes, chunks, owner = {}, [], []
    for pid in ARXIV:
        f = folder / (pid + '.pdf')
        if not f.exists():
            urllib.request.urlretrieve('https://arxiv.org/pdf/' + pid, f)
        hashes[pid] = hashlib.sha256(f.read_bytes()).hexdigest()
        for c in chunk_pages(read_pdf(f), size=CHUNK, overlap=50):
            chunks.append(c)
            owner.append(pid)
    texts = [norm(c.text) for c in chunks]
    emb = LocalEmbedder(a.cache_dir, a.offline)
    t = time.time()
    vectors = [unit(v) for v in emb.embed([c.text for c in chunks])]
    ranker = HybridRanker([c.text for c in chunks], vectors)
    cases = json.loads((root / 'eval/hybrid_cases.json').read_text())
    per = {m: [] for m in ranker.METHODS}
    skipped = []
    for pid, question, evidence in cases:
        relevant = {i for i, (x, o) in enumerate(zip(texts, owner)) if o == pid and norm(evidence) in x}
        if not relevant:
            skipped.append(question)
            continue
        qv = unit(emb.embed([question])[0])
        for m in ranker.METHODS:
            per[m].append(metrics(ranker.order(question, qv, m), relevant))
    summary = {m: {k: round(mean([r[k] for r in rows]), 3) for k in rows[0]} | {'mrr': round(mean([r['rr'] for r in rows]), 3)}
               for m, rows in per.items()}
    for v in summary.values():
        v.pop('rr')
    result = {'corpus_sha256': hashes, 'chunks': len(chunks), 'questions_scored': len(per['dense']),
              'questions_skipped_no_evidence_chunk': skipped, 'metrics': summary,
              'note': 'Author-labelled, 4 papers, same-document relevance by evidence string. Not a general benchmark.'}
    text = json.dumps(result, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text + '\n')


if __name__ == '__main__':
    main()
