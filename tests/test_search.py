import math
import unittest
from docchat.pdf import Chunk
from docchat.search import Index, unit


class StubEmbedder:
    def __init__(self, values):
        self.values = values
    def embed(self, texts):
        return [self.values[t] for t in texts]


class SearchTests(unittest.TestCase):
    def chunks(self):
        return [Chunk(1, 0, 3, 'fee'), Chunk(2, 10, 16, 'refund')]

    def test_cosine_ranking_and_provenance(self):
        index = Index(self.chunks(), StubEmbedder({'fee': [1,0], 'refund': [0,5], 'return': [0,2]}))
        matches = index.search('return', k=1)
        self.assertEqual((matches[0].page, matches[0].start, matches[0].text), (2, 10, 'refund'))
        self.assertAlmostEqual(matches[0].score, 1)

    def test_stable_ties(self):
        index = Index(self.chunks(), StubEmbedder({'fee': [1], 'refund': [1], 'q': [1]}))
        self.assertEqual([m.page for m in index.search('q')], [1,2])

    def test_empty_index_does_not_call_model(self):
        self.assertEqual(Index([], None).search('question'), [])

    def test_invalid_query_and_k(self):
        index = Index([], None)
        for q,k in [(' ',1), ('q',0), ('q',21), ('q',True)]:
            with self.subTest(q=q,k=k), self.assertRaises(ValueError): index.search(q,k)

    def test_bad_vectors(self):
        for vector in [[],[0,0],[math.nan],[math.inf]]:
            with self.subTest(vector=vector), self.assertRaises(ValueError): unit(vector)

    def test_mixed_dimensions_rejected(self):
        with self.assertRaises(ValueError):
            Index(self.chunks(), StubEmbedder({'fee':[1], 'refund':[1,0]}))

    def test_query_dimension_rejected(self):
        index = Index(self.chunks(), StubEmbedder({'fee':[1], 'refund':[1], 'q':[1,0]}))
        with self.assertRaises(ValueError): index.search('q')

    def test_count_mismatch(self):
        class Broken:
            def embed(self,texts): return [[1]]
        with self.assertRaises(ValueError): Index(self.chunks(), Broken())

    def test_negative_similarity_is_preserved_not_confidence(self):
        index = Index([self.chunks()[0]], StubEmbedder({'fee':[1], 'opposite':[-1]}))
        self.assertEqual(index.search('opposite')[0].score, -1)
