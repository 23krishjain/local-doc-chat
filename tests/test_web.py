import http.client
import json
import threading
import unittest

from docchat.pdf import DocumentError
from docchat.web import make_server


def stub_answer(data, question):
    if question == 'explode':
        raise OSError('disk gone')
    if question == 'bad':
        raise ValueError('bad question')
    return {'status': 'answered', 'echo_q': question, 'bytes': len(data)}


class WebTests(unittest.TestCase):
    def start(self, answer_func=stub_answer, **kwargs):
        server = make_server(0, answer_func, **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def request(self, port, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request(method, path, body=body)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_home_page_served(self):
        status, data = self.request(self.start(), 'GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'local-doc-chat', data)
        self.assertIn(b'type="file"', data)

    def test_unknown_paths_404(self):
        port = self.start()
        self.assertEqual(self.request(port, 'GET', '/nope')[0], 404)
        self.assertEqual(self.request(port, 'POST', '/nope', body=b'x')[0], 404)

    def test_ask_roundtrip(self):
        status, data = self.request(self.start(), 'POST', '/ask?q=refund%3F',
                                    body=b'%PDF-fake')
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual((payload['echo_q'], payload['bytes']), ('refund?', 9))

    def test_pipeline_value_error_422(self):
        status, data = self.request(self.start(), 'POST', '/ask?q=bad', body=b'x')
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(data)['error'], 'ValueError')

    def test_pipeline_error_leaks_type_only(self):
        status, data = self.request(self.start(), 'POST', '/ask?q=explode', body=b'x')
        self.assertEqual(status, 422)
        self.assertNotIn('disk gone', json.loads(data)['error'])

    def test_missing_or_oversize_body_400(self):
        port = self.start(max_bytes=4)
        self.assertEqual(self.request(port, 'POST', '/ask?q=x', body=b'12345')[0], 400)
        self.assertEqual(self.request(port, 'POST', '/ask?q=x')[0], 400)

    def test_oversize_question_400(self):
        port = self.start()
        self.assertEqual(self.request(port, 'POST', '/ask?q=' + 'a' * 2001,
                                      body=b'x')[0], 400)

    def test_refuses_non_loopback(self):
        with self.assertRaises(ValueError):
            make_server(0, stub_answer, host='0.0.0.0')


if __name__ == '__main__':
    unittest.main()


class StubLibrary:
    """Library-shaped stub: no model, no filesystem."""

    def __init__(self):
        self.docs = []

    def documents(self):
        return [dict(d) for d in self.docs]

    def add_bytes(self, data):
        if data == b'explode':
            raise OSError('disk gone')
        if data == b'bad':
            raise ValueError('not a pdf')
        meta = {'source_sha256': 'ab' * 32, 'pages': 2, 'chunks': 4,
                'no_text_pages': [], 'embedded': True}
        self.docs.append({'source_sha256': meta['source_sha256'], 'pages': 2,
                          'chunks': 4, 'no_text_pages': []})
        return meta

    def ask(self, question, min_score=0.34, k=3):
        if question == 'explode':
            raise RuntimeError('model blew up')
        return {'status': 'answered', 'question': question,
                'documents': len(self.docs), 'chunks': 0,
                'min_score': min_score, 'k': k, 'citations': []}


class ExplodingDocumentsLibrary(StubLibrary):
    def documents(self):
        raise DocumentError('corrupt cache file deadbeef: re-add the document')


class LibraryWebTests(unittest.TestCase):
    def start(self, library=None, **kwargs):
        server = make_server(0, library=library or StubLibrary(), **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def request(self, port, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        conn.request(method, path, body=body)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, data

    def test_library_page_served(self):
        status, data = self.request(self.start(), 'GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'local-doc-chat library', data)
        self.assertIn(b'/library/ask', data)
        self.assertIn(b'/documents', data)

    def test_add_then_documents_listed(self):
        library = StubLibrary()
        port = self.start(library)
        status, data = self.request(port, 'POST', '/library/add', body=b'%PDF-fake')
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload['source_sha256'], 'ab' * 32)
        self.assertTrue(payload['embedded'])
        status, data = self.request(port, 'GET', '/documents')
        self.assertEqual(status, 200)
        docs = json.loads(data)['documents']
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]['chunks'], 4)

    def test_add_error_leaks_type_only(self):
        status, data = self.request(self.start(), 'POST', '/library/add',
                                    body=b'explode')
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(data)['error'], 'OSError')

    def test_add_value_error_422(self):
        status, data = self.request(self.start(), 'POST', '/library/add',
                                    body=b'bad')
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(data)['error'], 'ValueError')

    def test_add_missing_or_oversize_body_400(self):
        port = self.start(max_bytes=4)
        self.assertEqual(self.request(port, 'POST', '/library/add')[0], 400)
        self.assertEqual(
            self.request(port, 'POST', '/library/add', body=b'12345')[0], 400)

    def test_ask_roundtrip_with_k(self):
        port = self.start()
        status, data = self.request(port, 'POST', '/library/ask?q=refund%3F&k=5')
        self.assertEqual(status, 200)
        payload = json.loads(data)
        self.assertEqual(payload['question'], 'refund?')
        self.assertEqual(payload['k'], 5)

    def test_ask_blank_and_bad_k_400(self):
        port = self.start()
        self.assertEqual(self.request(port, 'POST', '/library/ask?q=%20')[0], 400)
        self.assertEqual(self.request(port, 'POST', '/library/ask?q=x&k=0')[0], 400)
        self.assertEqual(
            self.request(port, 'POST', '/library/ask?q=x&k=nope')[0], 400)

    def test_ask_oversize_question_400(self):
        port = self.start()
        self.assertEqual(
            self.request(port, 'POST', '/library/ask?q=' + 'a' * 2001)[0], 400)

    def test_ask_pipeline_error_leaks_type_only(self):
        status, data = self.request(self.start(), 'POST',
                                    '/library/ask?q=explode')
        self.assertEqual(status, 422)
        payload = json.loads(data)
        self.assertEqual(payload['error'], 'RuntimeError')
        self.assertNotIn('blew up', json.dumps(payload))

    def test_documents_corrupt_cache_422(self):
        port = self.start(ExplodingDocumentsLibrary())
        status, data = self.request(port, 'GET', '/documents')
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(data)['error'], 'DocumentError')

    def test_single_upload_route_404_in_library_mode(self):
        port = self.start()
        self.assertEqual(
            self.request(port, 'POST', '/ask?q=x', body=b'%PDF-1')[0], 404)
        self.assertEqual(self.request(port, 'GET', '/ask')[0], 404)

    def test_library_mode_refuses_non_loopback(self):
        with self.assertRaises(ValueError):
            make_server(0, library=StubLibrary(), host='0.0.0.0')

    def test_neither_handler_nor_library_rejected(self):
        with self.assertRaises(ValueError):
            make_server(0)
