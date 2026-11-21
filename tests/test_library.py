import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import docchat.library as libmod
from docchat.library import Library
from docchat.pdf import DocumentError
from pdf_fixtures import make_pdf


class StubEmbedder:
    def __init__(self, table):
        self.table = table
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [self.table[t] for t in texts]


def pdf_bytes(tmp, name, texts):
    path = Path(tmp) / name
    make_pdf(path, texts)
    return path.read_bytes()


def only_text(pages):
    """Single-chunk fixture text, mirroring the parser's exact output."""
    return pages


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / 'store'
        self.alpha = pdf_bytes(self.tmp.name, 'a.pdf', ['alpha fee'])
        self.beta = pdf_bytes(self.tmp.name, 'b.pdf', ['beta refund'])
        self.sha_a = hashlib.sha256(self.alpha).hexdigest()
        self.sha_b = hashlib.sha256(self.beta).hexdigest()
        # Parse once to learn the exact chunk text the parser produces.
        from docchat.pdf import read_pdf, chunk_pages
        pages_a = read_pdf(Path(self.tmp.name) / 'a.pdf')
        pages_b = read_pdf(Path(self.tmp.name) / 'b.pdf')
        self.text_a = chunk_pages(pages_a, size=500, overlap=75)[0].text
        self.text_b = chunk_pages(pages_b, size=500, overlap=75)[0].text
        self.embedder = StubEmbedder({self.text_a: [1.0, 0.0],
                                      self.text_b: [0.0, 1.0],
                                      'q': [0.0, 1.0], 'q2': [1.0, 1.0]})

    def library(self, **kwargs):
        return Library(self.store, embedder=self.embedder, **kwargs)

    def test_add_persists_and_reuses_trusted_cache(self):
        lib = self.library()
        first = lib.add_bytes(self.alpha)
        self.assertTrue(first['embedded'])
        self.assertTrue((self.store / (self.sha_a + '.json')).exists())
        calls = self.embedder.calls
        second = lib.add_bytes(self.alpha)
        self.assertFalse(second['embedded'])
        self.assertEqual(self.embedder.calls, calls)

    def test_index_loads_without_embedder(self):
        self.library().add_bytes(self.alpha)
        fresh = Library(self.store)  # no embedder: cache must suffice
        index = fresh.index()
        self.assertEqual(len(index.chunks), 1)
        self.assertEqual(index.chunks[0].source, self.sha_a)

    def test_ask_cites_owning_document(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        lib.add_bytes(self.beta)
        out = lib.ask('q', 0.5)
        self.assertEqual(out['status'], 'answered')
        self.assertEqual(out['documents'], 2)
        self.assertEqual(out['citations'][0]['source_sha256'], self.sha_b)
        self.assertEqual(out['citations'][0]['text'], self.text_b)

    def test_abstains_with_per_document_provenance(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        lib.add_bytes(self.beta)
        # q2 scores ~0.707 against both docs, below a 0.9 gate.
        out = lib.ask('q2', 0.9)
        self.assertEqual(out['status'], 'insufficient_evidence')
        sources = {e['source'] for e in out['nearest_evidence']}
        self.assertEqual(sources, {self.sha_a, self.sha_b})

    def test_corrupt_cache_fails_loud_then_repairs_on_add(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        (self.store / (self.sha_a + '.json')).write_text('not json')
        with self.assertRaises(DocumentError):
            lib.index()
        with self.assertRaises(DocumentError):
            lib.documents()
        repaired = lib.add_bytes(self.alpha)
        self.assertTrue(repaired['embedded'])
        self.assertEqual(len(lib.documents()), 1)

    def test_model_mismatch_reembeds(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        path = self.store / (self.sha_a + '.json')
        payload = json.loads(path.read_text())
        payload['model'] = 'some-other-model'
        path.write_text(json.dumps(payload))
        calls = self.embedder.calls
        self.assertTrue(lib.add_bytes(self.alpha)['embedded'])
        self.assertGreater(self.embedder.calls, calls)

    def test_tampered_vector_rejected(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        path = self.store / (self.sha_a + '.json')
        payload = json.loads(path.read_text())
        payload['chunks'][0]['vector'][0] = float('nan')
        path.write_text(json.dumps(payload))
        with self.assertRaises(DocumentError):
            lib.index()

    def test_total_chunk_cap_enforced(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        with mock.patch.object(libmod, 'MAX_TOTAL_CHUNKS', 1):
            with self.assertRaises(DocumentError):
                lib.add_bytes(self.beta)
        lib.add_bytes(self.beta)  # under the real cap the add succeeds
        with mock.patch.object(libmod, 'MAX_TOTAL_CHUNKS', 1):
            with self.assertRaises(DocumentError):
                lib.index()

    def test_remove_validates_hash(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        self.assertTrue(lib.remove(self.sha_a))
        self.assertFalse(lib.remove(self.sha_a))
        for bad in ['../escape', '../../etc/passwd', 'A' * 64, 'zz' + '0' * 62, '']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                lib.remove(bad)

    def test_empty_library_ask_abstains(self):
        out = self.library().ask('anything?', 0.5)
        self.assertEqual(out['status'], 'insufficient_evidence')
        self.assertEqual(out['documents'], 0)
        self.assertEqual(out['chunks'], 0)

    def test_oversize_input_rejected(self):
        with self.assertRaises(DocumentError):
            self.library().add_bytes(b'x' * (20 * 1024 * 1024 + 1))

    def test_citation_binding_detects_wrong_document(self):
        lib = self.library()
        lib.add_bytes(self.alpha)
        lib.add_bytes(self.beta)
        out = lib.ask('q', 0.5)
        citation = dict(out['citations'][0])
        self.assertTrue(Library._bound(libmod.Citation(**citation),
                                       lib.index(self.embedder).search('q', 3)))
        citation['source_sha256'] = self.sha_a  # quote is from beta, not alpha
        self.assertFalse(Library._bound(libmod.Citation(**citation),
                                        lib.index(self.embedder).search('q', 3)))


if __name__ == '__main__':
    unittest.main()
