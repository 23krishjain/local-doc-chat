import base64
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from docchat.client import image_question, encode_image, ChatError

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jM1sAAAAASUVORK5CYII=')


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.image = Path(self.tmp.name) / 'tiny.png'
        self.image.write_bytes(PNG)

    def server(self, payload, status=200, location=None):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                if location:
                    self.send_header('Location', location)
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}', seen

    def test_real_http_request_shape_and_answer(self):
        endpoint, seen = self.server(b'{"message":{"content":"A white pixel."}}')
        self.assertEqual(image_question(self.image, 'What is visible?', endpoint=endpoint), 'A white pixel.')
        route, body = seen[0]
        self.assertEqual(route, '/api/chat')
        self.assertFalse(body['stream'])
        self.assertEqual(base64.b64decode(body['messages'][1]['images'][0]), PNG)
        self.assertEqual(body['model'], 'qwen2.5vl:7b')

    def test_model_override(self):
        endpoint, seen = self.server(b'{"message":{"content":"ok"}}')
        image_question(self.image, 'Describe', model='qwen2.5vl:3b', endpoint=endpoint)
        self.assertEqual(seen[0][1]['model'], 'qwen2.5vl:3b')

    def test_remote_endpoints_rejected(self):
        for endpoint in ['https://example.com', 'http://example.com', 'http://localhost@evil.test', 'http://localhost/path', 'http://localhost?x=y']:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                image_question(self.image, 'Describe', endpoint=endpoint)

    def test_blank_question(self):
        with self.assertRaises(ValueError):
            image_question(self.image, ' ')

    def test_nonimage_rejected(self):
        self.image.write_text('not an image')
        with self.assertRaises(ValueError):
            encode_image(self.image)

    def test_large_image_rejected(self):
        with self.image.open('wb') as f:
            f.truncate(10 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            encode_image(self.image)

    def test_missing_image(self):
        with self.assertRaises(FileNotFoundError):
            encode_image(self.image.with_name('missing.png'))

    def test_error_response(self):
        endpoint, _ = self.server(b'{"error":"model not found"}', 404)
        with self.assertRaisesRegex(ChatError, 'HTTP 404'):
            image_question(self.image, 'Describe', endpoint=endpoint)

    def test_invalid_responses(self):
        for response in [b'not json', b'{}', b'{"message":{"content":null}}', b'{"message":{"content":""}}']:
            with self.subTest(response=response):
                endpoint, _ = self.server(response)
                with self.assertRaises(ChatError):
                    image_question(self.image, 'Describe', endpoint=endpoint)

    def test_response_size_limit(self):
        endpoint, _ = self.server(b'x' * (1024 * 1024 + 1))
        with self.assertRaisesRegex(ChatError, 'exceeded'):
            image_question(self.image, 'Describe', endpoint=endpoint)

    def test_redirect_is_not_followed(self):
        target, target_seen = self.server(b'{"message":{"content":"leaked"}}')
        endpoint, _ = self.server(b'', 307, target)
        with self.assertRaisesRegex(ChatError, 'HTTP 307'):
            image_question(self.image, 'Describe', endpoint=endpoint)
        self.assertEqual(target_seen, [])
