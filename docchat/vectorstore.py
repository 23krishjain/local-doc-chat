"""Persistent vector store: SQLite holds vectors and metadata, an index answers queries.

Two interchangeable search backends over the same rows:
  exact  numpy inner product over all vectors (ground truth, no extra dependency)
  hnsw   FAISS IndexHNSWFlat (approximate; optional `faiss-cpu`)
The index is rebuilt from SQLite on open, so SQLite is the only source of truth.
Vectors must be unit length, so inner product equals cosine similarity.
"""
from contextlib import closing
import sqlite3

import numpy as np


class VectorStore:
    def __init__(self, path, dim, *, backend='exact', m=32, ef_construction=200, ef_search=64):
        if backend not in ('exact', 'hnsw'):
            raise ValueError("backend must be 'exact' or 'hnsw'")
        if type(dim) is not int or dim <= 0:
            raise ValueError('dim must be a positive integer')
        self.path, self.dim, self.backend = str(path), dim, backend
        self.params = (m, ef_construction, ef_search)
        with closing(self._con()) as con:
            con.execute('CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)')
            con.execute('''CREATE TABLE IF NOT EXISTS items (
                key TEXT PRIMARY KEY, doc TEXT NOT NULL, text TEXT NOT NULL, vec BLOB NOT NULL)''')
            con.execute('CREATE INDEX IF NOT EXISTS items_doc ON items(doc)')
            row = con.execute("SELECT v FROM meta WHERE k='dim'").fetchone()
            if row and int(row[0]) != dim:
                raise ValueError('store holds %s-dimensional vectors' % row[0])
            con.execute("INSERT OR IGNORE INTO meta VALUES ('dim', ?)", (str(dim),))
            con.commit()
        self._load()

    def _con(self):
        con = sqlite3.connect(self.path, timeout=5)
        con.execute('PRAGMA journal_mode=WAL')
        return con

    def _load(self):
        with closing(self._con()) as con:
            rows = con.execute('SELECT key, doc, text, vec FROM items ORDER BY rowid').fetchall()
        self.keys = [r[0] for r in rows]
        self.docs = [r[1] for r in rows]
        self.texts = [r[2] for r in rows]
        self.matrix = (np.frombuffer(b''.join(r[3] for r in rows), dtype='<f4').reshape(len(rows), self.dim)
                       if rows else np.zeros((0, self.dim), dtype='<f4'))
        self._build()

    def _build(self):
        self.index = None
        if self.backend == 'hnsw' and len(self.keys):
            import faiss
            m, efc, efs = self.params
            index = faiss.IndexHNSWFlat(self.dim, m, faiss.METRIC_INNER_PRODUCT)
            index.hnsw.efConstruction, index.hnsw.efSearch = efc, efs
            index.add(np.ascontiguousarray(self.matrix))
            self.index = index

    def _check(self, vector):
        v = np.asarray(vector, dtype='<f4')
        if v.shape != (self.dim,) or not np.isfinite(v).all():
            raise ValueError('vector must be finite with %d dimensions' % self.dim)
        if abs(float(np.linalg.norm(v)) - 1.0) > 1e-3:
            raise ValueError('vector must be unit length')
        return v

    def add(self, doc, items):
        """items: iterable of (key, text, vector). Existing keys are left unchanged
        (content-addressed callers re-add the same chunk safely). Returns count added."""
        fresh = []
        known = set(self.keys)
        for key, text, vector in items:
            if not isinstance(key, str) or not key:
                raise ValueError('key must be a non-empty string')
            v = self._check(vector)
            if key not in known:
                known.add(key)
                fresh.append((key, doc, text, v))
        if not fresh:
            return 0
        with closing(self._con()) as con:
            with con:
                con.executemany('INSERT INTO items(key,doc,text,vec) VALUES (?,?,?,?)',
                                [(k, d, t, v.tobytes()) for k, d, t, v in fresh])
        self._load()
        return len(fresh)

    def delete_document(self, doc):
        with closing(self._con()) as con:
            with con:
                n = con.execute('DELETE FROM items WHERE doc=?', (doc,)).rowcount
        if n:
            self._load()
        return n

    def __len__(self):
        return len(self.keys)

    def search(self, vector, k=5):
        if type(k) is not int or k < 1:
            raise ValueError('k must be a positive integer')
        q = self._check(vector)
        k = min(k, len(self.keys))
        if k == 0:
            return []
        if self.backend == 'hnsw':
            scores, ids = self.index.search(q.reshape(1, -1), k)
            pairs = [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i >= 0]
        else:
            sims = self.matrix @ q
            order = np.lexsort((np.arange(len(sims)), -sims))[:k]
            pairs = [(int(i), float(sims[i])) for i in order]
        return [{'key': self.keys[i], 'doc': self.docs[i], 'text': self.texts[i], 'score': s} for i, s in pairs]
