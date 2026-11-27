import unittest

from docchat.rerank import rerank


def by_length(query, passages):
    return [len(p) for p in passages]


class RerankTests(unittest.TestCase):
    C = [(10, 'aa'), (11, 'aaaa'), (12, 'a')]

    def test_orders_by_score_and_returns_original_indexes(self):
        self.assertEqual(rerank('q', self.C, by_length), [11, 10, 12])

    def test_top_truncates(self):
        self.assertEqual(rerank('q', self.C, by_length, top=2), [11, 10])

    def test_ties_keep_first_stage_order(self):
        self.assertEqual(rerank('q', self.C, lambda q, p: [1, 1, 1]), [10, 11, 12])

    def test_query_and_passages_reach_scorer(self):
        seen = []
        rerank('what?', self.C, lambda q, p: seen.append((q, p)) or [0, 0, 0])
        self.assertEqual(seen, [('what?', ['aa', 'aaaa', 'a'])])

    def test_empty_candidates(self):
        self.assertEqual(rerank('q', [], by_length), [])

    def test_validation(self):
        with self.assertRaises(ValueError):
            rerank('q', self.C, lambda q, p: [1.0])
        with self.assertRaises(ValueError):
            rerank('q', self.C, lambda q, p: [1, float('nan'), 2])
        with self.assertRaises(ValueError):
            rerank('q', self.C, by_length, top=0)


class RealModelTests(unittest.TestCase):
    """Runs only when the cross-encoder is already cached locally (no download in tests)."""

    def test_relevant_passage_outranks_irrelevant(self):
        import os
        cache = os.environ.get('DOCCHAT_MODEL_CACHE')
        if not cache:
            self.skipTest('set DOCCHAT_MODEL_CACHE to a directory holding the cached model')
        from docchat.rerank import CrossEncoder
        enc = CrossEncoder(cache, offline=True)
        got = rerank('How many attention heads does the base model use?',
                     [(0, 'The cafeteria opens at noon and serves soup.'),
                      (1, 'The base model employs h = 8 parallel attention heads.')], enc.scores)
        self.assertEqual(got[0], 1)


if __name__ == '__main__':
    unittest.main()
