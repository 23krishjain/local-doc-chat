"""Lexical BM25, dense and hybrid (reciprocal rank fusion) ranking over chunks.

Pure ranking functions plus a small index. Scores from different methods are on
different scales, so fusion uses ranks only, never raw scores.
"""
from collections import Counter
import math
import re

TOKEN = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")
STOP = frozenset('a an and are as at be by for from how in is it of on or that the this to was what when which who why with does do did'.split())


def tokenize(text):
    return [t for t in TOKEN.findall(text.lower()) if t not in STOP]


class BM25:
    """Okapi BM25 with the non-negative idf variant, k1=1.5, b=0.75."""

    def __init__(self, texts, k1=1.5, b=0.75):
        if k1 < 0 or not 0 <= b <= 1:
            raise ValueError('k1 must be >= 0 and b within 0..1')
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(t)) for t in texts]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.docs)) if self.docs else 0.0
        df = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def scores(self, query):
        terms = set(tokenize(query))
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in terms:
                f = doc.get(t)
                if f:
                    norm = 1 - self.b + self.b * (length / self.avg if self.avg else 0)
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * norm)
            out.append(s)
        return out


def rank(scores, positive_only=False):
    """Indexes best first; ties break by lower index so results are deterministic."""
    order = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
    return [i for i in order if scores[i] > 0] if positive_only else order


def rrf(rankings, k=60, weights=None):
    """Reciprocal rank fusion: score(i) = sum_w w / (k + rank_i), rank from 1."""
    if k <= 0:
        raise ValueError('k must be positive')
    weights = weights or [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError('one weight per ranking')
    fused = Counter()
    for order, w in zip(rankings, weights):
        for pos, i in enumerate(order, start=1):
            fused[i] += w / (k + pos)
    return sorted(fused, key=lambda i: (-fused[i], i)), fused


class HybridRanker:
    """Ranks precomputed unit vectors and chunk texts by dense, bm25 or hybrid."""

    METHODS = ('dense', 'bm25', 'hybrid')

    def __init__(self, texts, vectors):
        if len(texts) != len(vectors):
            raise ValueError('texts and vectors must align')
        self.texts, self.vectors = list(texts), vectors
        self.bm25 = BM25(self.texts)

    def order(self, query, query_vector, method='hybrid', depth=100):
        if method not in self.METHODS:
            raise ValueError('method must be one of %s' % (self.METHODS,))
        dense = rank([sum(a * b for a, b in zip(query_vector, v)) for v in self.vectors])
        if method == 'dense':
            return dense[:depth]
        lexical = rank(self.bm25.scores(query), positive_only=True)
        if method == 'bm25':
            return lexical[:depth]
        return rrf([dense[:depth], lexical[:depth]])[0][:depth]
