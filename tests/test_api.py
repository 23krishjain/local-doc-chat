"""HTTP API tests with a library-shaped stub. No model, no filesystem."""
import json
import unittest

from fastapi.testclient import TestClient

from docchat.api import create_app
from docchat.pdf import DocumentError


class StubLibrary:
    def __init__(self):
        self.docs = []

    def documents(self):
        return [dict(d) for d in self.docs]

    def add_bytes(self, data):
        if data == b'explode':
            raise OSError('disk gone')
        if data == b'bad':
            raise ValueError('not a pdf')
        if data == b'nomodel':
            raise ImportError('no module named fastembed')
        meta = {'source_sha256': 'cd' * 32, 'pages': 2, 'chunks': 4,
                'no_text_pages': [], 'embedded': True}
        self.docs.append({'source_sha256': meta['source_sha256'], 'pages': 2,
                          'chunks': 4, 'no_text_pages': []})
        return meta

    def ask(self, question, min_score=0.34, k=3):
        if question == 'explode':
            raise RuntimeError('model blew up')
        if question == 'corrupt':
            raise DocumentError('corrupt cache file deadbeef: re-add it')
        return {'status': 'answered', 'question': question,
                'documents': len(self.docs), 'min_score': min_score,
                'k': k, 'citations': []}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.library = StubLibrary()
        self.client = TestClient(create_app(self.library))

    def test_health(self):
        response = self.client.get('/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_openapi_and_docs_disabled(self):
        self.assertEqual(self.client.get('/openapi.json').status_code, 404)
        self.assertEqual(self.client.get('/docs').status_code, 404)

    def test_add_then_documents(self):
        response = self.client.post('/documents', content=b'%PDF-fake')
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload['source_sha256'], 'cd' * 32)
        listing = self.client.get('/documents')
        self.assertEqual(listing.status_code, 200)
        docs = listing.json()['documents']
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['chunks'], 4)

    def test_add_missing_body_400(self):
        response = self.client.post('/documents')
        self.assertEqual(response.status_code, 400)

    def test_add_oversize_body_400(self):
        client = TestClient(create_app(StubLibrary(), max_bytes=4))
        response = client.post('/documents', content=b'12345')
        self.assertEqual(response.status_code, 400)

    def test_add_pipeline_errors_leak_type_only(self):
        response = self.client.post('/documents', content=b'explode')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'error': 'OSError'})
        response = self.client.post('/documents', content=b'bad')
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'error': 'ValueError'})

    def test_add_missing_dependency_500(self):
        response = self.client.post('/documents', content=b'nomodel')
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('fastembed', json.dumps(response.json()))

    def test_ask_roundtrip_with_defaults(self):
        response = self.client.post('/ask', json={'question': 'refund?'})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['question'], 'refund?')
        self.assertEqual(payload['k'], 3)

    def test_ask_with_k(self):
        response = self.client.post('/ask',
                                    json={'question': 'refund?', 'k': 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['k'], 5)

    def test_ask_validation_errors_422(self):
        for body in ({}, {'question': ''}, {'question': '   '},
                     {'question': 'x', 'k': 0}, {'question': 'x', 'k': 21},
                     {'question': 'x', 'k': 'lots'},
                     {'question': 'a' * 2001}):
            response = self.client.post('/ask', json=body)
            self.assertEqual(response.status_code, 422, body)
            payload = response.json()
            self.assertEqual(payload['error'], 'validation')
            self.assertTrue(payload['detail'])

    def test_validation_detail_never_echoes_input(self):
        secret = 'a' * 2001
        response = self.client.post('/ask', json={'question': secret})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, json.dumps(response.json()))

    def test_ask_pipeline_errors_leak_type_only(self):
        response = self.client.post('/ask', json={'question': 'explode'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'error': 'RuntimeError'})
        response = self.client.post('/ask', json={'question': 'corrupt'})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {'error': 'DocumentError'})

    def test_create_app_rejects_bad_min_score(self):
        with self.assertRaises(ValueError):
            create_app(StubLibrary(), min_score=1.5)


if __name__ == '__main__':
    unittest.main()
