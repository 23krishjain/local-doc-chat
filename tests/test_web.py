import http.client
import json
import threading
import unittest

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
