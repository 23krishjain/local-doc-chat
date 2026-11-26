from pathlib import Path
import tempfile
import unittest

import numpy as np

from docchat.vectorstore import VectorStore

try:
    import faiss  # noqa: F401
    HAVE_FAISS = True
except ImportError:
    HAVE_FAISS = False


def unit_rows(n, dim, seed):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, dim)).astype('f4')
    return x / np.linalg.norm(x, axis=1, keepdims=True)


class StoreBase(unittest.TestCase):
    backend = 'exact'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'v.db'
        self.vecs = unit_rows(40, 16, 1)
        self.s = VectorStore(self.path, 16, backend=self.backend)
        self.s.add('docA', [('a%d' % i, 'text a%d' % i, self.vecs[i]) for i in range(20)])
        self.s.add('docB', [('b%d' % i, 'text b%d' % i, self.vecs[20 + i]) for i in range(20)])

    def test_nearest_of_a_stored_vector_is_itself(self):
        hit = self.s.search(self.vecs[7], k=3)
        self.assertEqual(hit[0]['key'], 'a7')
        self.assertAlmostEqual(hit[0]['score'], 1.0, places=4)
        self.assertEqual(len(hit), 3)

    def test_restart_reloads_from_disk(self):
        again = VectorStore(self.path, 16, backend=self.backend)
        self.assertEqual(len(again), 40)
        self.assertEqual(again.search(self.vecs[25], k=1)[0]['key'], 'b5')

    def test_duplicate_keys_are_not_added_twice(self):
        n = self.s.add('docA', [('a0', 'text a0', self.vecs[0]), ('new', 'n', self.vecs[1])])
        self.assertEqual(n, 1)
        self.assertEqual(len(self.s), 41)

    def test_delete_document_removes_only_its_rows(self):
        self.assertEqual(self.s.delete_document('docA'), 20)
        self.assertEqual(len(self.s), 20)
        self.assertTrue(all(h['doc'] == 'docB' for h in self.s.search(self.vecs[3], k=20)))
        self.assertEqual(self.s.delete_document('docA'), 0)
        self.assertEqual(len(VectorStore(self.path, 16, backend=self.backend)), 20)

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.s.search(np.ones(16, 'f4'))  # not unit length
        with self.assertRaises(ValueError):
            self.s.search(self.vecs[0][:5])
        with self.assertRaises(ValueError):
            self.s.add('d', [('', 't', self.vecs[0])])
        bad = self.vecs[0].copy(); bad[0] = np.nan
        with self.assertRaises(ValueError):
            self.s.add('d', [('x', 't', bad)])
        with self.assertRaises(ValueError):
            self.s.search(self.vecs[0], k=0)
        with self.assertRaises(ValueError):
            VectorStore(self.path, 8, backend=self.backend)  # wrong dimension for stored data

    def test_failed_add_leaves_store_unchanged(self):
        with self.assertRaises(ValueError):
            self.s.add('d', [('ok', 't', self.vecs[0]), ('bad', 't', np.ones(16, 'f4'))])
        self.assertEqual(len(self.s), 40)

    def test_empty_store_returns_nothing(self):
        e = VectorStore(Path(self.tmp.name) / 'e.db', 16, backend=self.backend)
        self.assertEqual(e.search(self.vecs[0]), [])


@unittest.skipUnless(HAVE_FAISS, 'faiss-cpu not installed')
class HnswStoreTests(StoreBase):
    backend = 'hnsw'

    def test_matches_exact_top1_on_small_set(self):
        exact = VectorStore(self.path, 16, backend='exact')
        for i in range(0, 40, 5):
            self.assertEqual(self.s.search(self.vecs[i], k=1)[0]['key'], exact.search(self.vecs[i], k=1)[0]['key'])


class ExactStoreTests(StoreBase):
    def test_ties_break_by_insertion_order(self):
        s = VectorStore(Path(self.tmp.name) / 't.db', 4)
        v = np.array([1, 0, 0, 0], 'f4')
        s.add('d', [('x', 't', v), ('y', 't', v)])
        self.assertEqual([h['key'] for h in s.search(v, k=2)], ['x', 'y'])

    def test_bad_backend(self):
        with self.assertRaises(ValueError):
            VectorStore(self.path, 16, backend='annoy')


del StoreBase  # only the concrete subclasses run

if __name__ == '__main__':
    unittest.main()
