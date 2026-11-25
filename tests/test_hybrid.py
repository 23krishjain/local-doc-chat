import unittest

from docchat.hybrid import BM25, HybridRanker, rank, rrf, tokenize
from docchat.pdf import Chunk
from docchat.search import Index


class Bm25Tests(unittest.TestCase):
    def test_tokenize_lowercases_and_drops_stopwords(self):
        self.assertEqual(tokenize('What is the Adam optimizer?'), ['adam', 'optimizer'])

    def test_rare_term_beats_common_term(self):
        b = BM25(['the cat sat', 'the dog sat', 'zebra crossing sat'])
        s = b.scores('zebra sat')
        self.assertEqual(rank(s)[0], 2)

    def test_repeated_term_saturates(self):
        b = BM25(['apple ' * 50 + 'x', 'apple y'])
        s = b.scores('apple')
        self.assertLess(s[0], 3 * s[1])

    def test_length_normalisation_prefers_short_doc_on_equal_tf(self):
        b = BM25(['apple', 'apple ' + 'pad ' * 40])
        s = b.scores('apple')
        self.assertGreater(s[0], s[1])

    def test_no_match_scores_zero_and_positive_only_is_empty(self):
        b = BM25(['alpha', 'beta'])
        self.assertEqual(rank(b.scores('gamma'), positive_only=True), [])

    def test_empty_corpus_and_bad_params(self):
        self.assertEqual(BM25([]).scores('x'), [])
        with self.assertRaises(ValueError):
            BM25(['a'], b=2)


class FusionTests(unittest.TestCase):
    def test_rrf_hand_computed(self):
        order, score = rrf([[0, 1, 2], [2, 1, 0]], k=60)
        self.assertEqual(order, [0, 2, 1])  # RRF favours a top rank over a steady middle rank
        self.assertAlmostEqual(score[1], 2 / 62)
        self.assertAlmostEqual(score[0], 1 / 61 + 1 / 63)

    def test_rrf_item_in_one_list_still_appears(self):
        order, _ = rrf([[0], [1]])
        self.assertEqual(order, [0, 1])  # tie breaks by index

    def test_rrf_weights_and_validation(self):
        order, _ = rrf([[0, 1], [1, 0]], weights=[1, 3])
        self.assertEqual(order[0], 1)
        with self.assertRaises(ValueError):
            rrf([[0]], k=0)
        with self.assertRaises(ValueError):
            rrf([[0]], weights=[1, 2])

    def test_rank_ties_are_deterministic(self):
        self.assertEqual(rank([1, 1, 1]), [0, 1, 2])


class RankerTests(unittest.TestCase):
    TEXTS = ['battery lasts ten hours', 'refund within thirty days', 'model ZX-9 manual']
    # Vectors make the dense side prefer doc 0 for the query vector (1,0).
    VECS = [(1.0, 0.0), (0.0, 1.0), (0.6, 0.8)]

    def test_methods_differ_and_hybrid_combines(self):
        r = HybridRanker(self.TEXTS, self.VECS)
        self.assertEqual(r.order('zx-9', (1.0, 0.0), 'dense')[0], 0)
        self.assertEqual(r.order('zx-9', (1.0, 0.0), 'bm25'), [2])
        self.assertIn(2, r.order('zx-9', (1.0, 0.0), 'hybrid')[:2])

    def test_validation(self):
        with self.assertRaises(ValueError):
            HybridRanker(['a'], [])
        with self.assertRaises(ValueError):
            HybridRanker(['a'], [(1.0,)]).order('a', (1.0,), 'nope')


class FakeEmbedder:
    def embed(self, texts):
        return [(1.0, 0.0) if 'alpha' in t else (0.0, 1.0) for t in texts]


class IndexMethodTests(unittest.TestCase):
    def setUp(self):
        chunks = [Chunk(1, 0, 5, 'alpha beta'), Chunk(1, 5, 12, 'gamma serial QX7 code')]
        self.index = Index(chunks, FakeEmbedder())

    def test_default_is_unchanged_dense(self):
        self.assertEqual(self.index.search('alpha', k=1)[0].text, 'alpha beta')

    def test_bm25_finds_exact_identifier(self):
        self.assertEqual(self.index.search('QX7', k=1, method='bm25')[0].text, 'gamma serial QX7 code')

    def test_hybrid_returns_k_results(self):
        self.assertEqual(len(self.index.search('QX7', k=2, method='hybrid')), 2)


if __name__ == '__main__':
    unittest.main()
