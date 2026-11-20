import math
import unittest
from docchat.answer import (Citation, answer_bytes, build_answer,
                            check_min_score, citation_for, is_valid_citation)
from docchat.pdf import DocumentError
from pdf_fixtures import make_pdf
from docchat.search import Match

HASH = 'a' * 64


def match(score, page=1, text='fee is INR 40', start=0, end=13):
    return Match(page, start, end, text, score)


class GateTests(unittest.TestCase):
    def test_answered_cites_exact_retrieved_passage(self):
        matches = [match(0.61, page=2, text='refund in 7 days', start=10, end=26),
                   match(0.40)]
        out = build_answer('refund?', matches, HASH, 0.34)
        self.assertEqual(out['status'], 'answered')
        self.assertEqual(out['excerpt'], 'refund in 7 days')
        self.assertEqual(out['citations'][0],
                         {'page': 2, 'start': 10, 'end': 26,
                          'text': 'refund in 7 days', 'score': 0.61,
                          'source_sha256': HASH})

    def test_only_supporting_matches_cited(self):
        out = build_answer('q', [match(0.5), match(0.2, page=2, text='x')], HASH, 0.34)
        self.assertEqual([c['page'] for c in out['citations']], [1])

    def test_boundary_inclusive(self):
        self.assertEqual(build_answer('q', [match(0.34)], HASH, 0.34)['status'], 'answered')

    def test_abstains_below_threshold_with_labelled_evidence(self):
        out = build_answer('q', [match(0.29), match(0.1, page=2, text='y')], HASH, 0.34)
        self.assertEqual(out['status'], 'insufficient_evidence')
        self.assertEqual(out['citations'], [])
        self.assertTrue(all(e['below_threshold'] for e in out['nearest_evidence']))
        self.assertEqual(out['nearest_evidence'][0]['score'], 0.29)

    def test_abstains_on_no_matches(self):
        out = build_answer('q', [], HASH, 0.34)
        self.assertEqual(out['status'], 'insufficient_evidence')
        self.assertEqual(out['nearest_evidence'], [])

    def test_blank_question_rejected(self):
        with self.assertRaises(ValueError):
            build_answer(' ', [match(0.9)], HASH, 0.34)

    def test_min_score_validation(self):
        for bad in [True, '0.5', None, math.nan, math.inf, -0.1, 1.1]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_min_score(bad)
        self.assertEqual(check_min_score(0), 0.0)
        self.assertEqual(check_min_score(1), 1.0)


class CitationTests(unittest.TestCase):
    def test_roundtrip_valid(self):
        m = match(0.5)
        self.assertTrue(is_valid_citation(citation_for(m, HASH), [m], HASH))

    def test_rejects_tampered_fields(self):
        m = match(0.5)
        tampered = [Citation(2, m.start, m.end, m.text, m.score, HASH),
                    Citation(m.page, 1, m.end, m.text, m.score, HASH),
                    Citation(m.page, m.start, m.end, 'changed', m.score, HASH),
                    Citation(m.page, m.start, m.end, m.text, 0.9, HASH),
                    Citation(m.page, m.start, m.end, m.text, m.score, 'b' * 64)]
        for citation in tampered:
            with self.subTest(citation=citation):
                self.assertFalse(is_valid_citation(citation, [m], HASH))

    def test_rejects_foreign_match(self):
        foreign = citation_for(match(0.5, text='elsewhere'), HASH)
        self.assertFalse(is_valid_citation(foreign, [match(0.5)], HASH))

    def test_rejects_non_citation(self):
        self.assertFalse(is_valid_citation({'page': 1}, [match(0.5)], HASH))


class AnswerBytesTests(unittest.TestCase):
    def test_no_text_pdf_abstains_without_model(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'blank.pdf'
            make_pdf(path, [None])
            out = answer_bytes(path.read_bytes(), 'anything?')
        self.assertEqual(out['status'], 'insufficient_evidence')
        self.assertEqual(out['chunks'], 0)
        self.assertEqual(out['no_text_pages'], [1])

    def test_oversize_input_rejected_before_parsing(self):
        with self.assertRaises(DocumentError):
            answer_bytes(b'x' * (20 * 1024 * 1024 + 1), 'q')

    def test_bad_k_rejected(self):
        for k in [0, 21, True, '3']:
            with self.subTest(k=k), self.assertRaises(ValueError):
                answer_bytes(b'%PDF', 'q', k=k)


if __name__ == '__main__':
    unittest.main()
