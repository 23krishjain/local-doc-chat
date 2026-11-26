"""HNSW (FAISS) vs exact search over MiniLM vectors of real public arXiv papers.

Reports recall@10 of HNSW against exact top-10 (same vectors, so this measures the
approximation only, not answer quality) and median/p95 query latency for each
backend. Queries are chunks sampled from the corpus with a fixed seed, embedded
as passages, not user questions. Numbers are for this machine and corpus only.
Run: python eval/vectorstore_eval.py --pdfs DIR --cache-dir D --out FILE
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from docchat.pdf import DocumentError, chunk_pages, read_pdf
from docchat.search import LocalEmbedder, unit
from docchat.vectorstore import VectorStore


def pct(xs, p):
    return float(np.percentile(xs, p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdfs', required=True)
    ap.add_argument('--cache-dir')
    ap.add_argument('--out')
    ap.add_argument('--queries', type=int, default=300)
    ap.add_argument('--budget-seconds', type=float, default=1e9, help='stop after this long and resume on rerun')
    ap.add_argument('--cache-npz', help='reuse embeddings from this file if present')
    a = ap.parse_args()
    files = sorted(Path(a.pdfs).glob('*.pdf'))
    texts, docs = [], []
    used = []
    for f in files:
        try:
            pages = read_pdf(f)
        except DocumentError:
            continue
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        used.append(digest)
        for c in chunk_pages(pages, size=300, overlap=50):
            if c.text.strip():
                texts.append(c.text)
                docs.append(digest)
    npz = Path(a.cache_npz) if a.cache_npz else None
    if npz and npz.exists():
        vecs = np.load(npz)['v']
        assert len(vecs) == len(texts)
    else:
        emb = LocalEmbedder(a.cache_dir)
        part = Path(str(npz) + '.part.npy') if npz else None
        done = list(np.load(part)) if part and part.exists() else []
        deadline = time.time() + a.budget_seconds
        while len(done) < len(texts):
            block = texts[len(done):len(done) + 500]
            done.extend(unit(v) for v in emb.embed(block))
            if part:
                np.save(part, np.array(done, dtype='f4'))
            if time.time() > deadline and len(done) < len(texts):
                print('partial: %d/%d embedded; rerun to continue' % (len(done), len(texts)))
                return
        vecs = np.array(done, dtype='f4')
        if npz:
            np.savez(npz, v=vecs)
    results = {'documents': len(used), 'chunks': len(texts), 'dim': int(vecs.shape[1]),
               'queries': a.queries, 'machine': platform.processor() or platform.machine(),
               'python': platform.python_version()}
    rng = np.random.default_rng(0)
    qi = rng.choice(len(texts), size=min(a.queries, len(texts)), replace=False)
    with tempfile.TemporaryDirectory() as d:
        stores = {}
        for name in ('exact', 'hnsw'):
            s = VectorStore(Path(d) / (name + '.db'), vecs.shape[1], backend=name)
            t = time.perf_counter()
            s.add('corpus', [('%d' % i, texts[i], vecs[i]) for i in range(len(texts))])
            results[name + '_build_and_load_seconds'] = round(time.perf_counter() - t, 2)
            stores[name] = s
        truth = {}
        lat = {'exact': [], 'hnsw': []}
        hits = {k: 0 for k in (1, 10)}
        for i in qi:
            q = vecs[i]
            for name in ('exact', 'hnsw'):
                t = time.perf_counter()
                r = stores[name].search(q, k=10)
                lat[name].append((time.perf_counter() - t) * 1000)
                truth[name] = [h['key'] for h in r]
            hits[10] += len(set(truth['exact']) & set(truth['hnsw']))
            hits[1] += truth['exact'][0] == truth['hnsw'][0]
        n = len(qi)
        results['hnsw_recall@10_vs_exact'] = round(hits[10] / (10 * n), 4)
        results['hnsw_top1_agrees_with_exact'] = round(hits[1] / n, 4)
        for name in lat:
            results[name + '_latency_ms'] = {'median': round(pct(lat[name], 50), 3), 'p95': round(pct(lat[name], 95), 3)}
        # Reopen from disk to show restart cost and identical answers.
        t = time.perf_counter()
        again = VectorStore(Path(d) / 'hnsw.db', vecs.shape[1], backend='hnsw')
        results['hnsw_reopen_seconds'] = round(time.perf_counter() - t, 2)
        results['reopen_top1_matches'] = again.search(vecs[qi[0]], 1)[0]['key'] == stores['hnsw'].search(vecs[qi[0]], 1)[0]['key']
    text = json.dumps(results, indent=2)
    print(text)
    if a.out:
        Path(a.out).write_text(text + '\n')


if __name__ == '__main__':
    main()
