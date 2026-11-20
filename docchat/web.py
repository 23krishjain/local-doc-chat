"""Loopback-only web UI over the cited-answer pipeline.

Trusted local inputs on a single-user machine. Binds 127.0.0.1/::1 only; it is
not hardened for network exposure, authentication or hostile PDFs. No uploads
leave the machine: the browser posts raw PDF bytes to this same process.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
from urllib.parse import urlparse, parse_qs

from .answer import DEFAULT_MIN_SCORE, answer_bytes, check_min_score
from .pdf import DocumentError

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_QUESTION_CHARS = 2000
LOOPBACK_HOSTS = {'127.0.0.1', '::1', 'localhost'}

PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>local-doc-chat</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem}
input[type=text]{width:100%;box-sizing:border-box;padding:.4rem}
pre{background:#f4f4f4;padding:1rem;white-space:pre-wrap;border:1px solid #ddd}</style></head>
<body>
<h1>local-doc-chat</h1>
<p>Pick a PDF and ask a question. The answer is an exact passage with page
citations, or <em>insufficient evidence</em>. Everything runs on this machine;
no upload leaves your computer.</p>
<p><input type="file" id="file" accept="application/pdf"></p>
<p><input type="text" id="q" maxlength="2000" placeholder="Question about the PDF"></p>
<button id="ask">Ask</button>
<pre id="out" aria-live="polite"></pre>
<script>
document.getElementById('ask').addEventListener('click', async () => {
  const out = document.getElementById('out');
  const f = document.getElementById('file').files[0];
  const q = document.getElementById('q').value;
  if (!f || !q.trim()) { out.textContent = 'Choose a PDF and type a question.'; return; }
  out.textContent = 'Working (first answer loads the local model)...';
  try {
    const r = await fetch('/ask?q=' + encodeURIComponent(q), {method: 'POST', body: f});
    const data = await r.json();
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) { out.textContent = 'Request failed: ' + e; }
});
</script>
</body></html>"""


def make_handler(answer_func, max_bytes=MAX_PDF_BYTES):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'docchat-local/0'

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == '/':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(PAGE)))
                self.end_headers()
                self.wfile.write(PAGE)
            else:
                self._json(404, {'error': 'not found'})

        def do_POST(self):
            if urlparse(self.path).path != '/ask':
                self._json(404, {'error': 'not found'})
                return
            params = parse_qs(urlparse(self.path).query)
            question = params.get('q', [''])[0]
            if len(question) > MAX_QUESTION_CHARS:
                self._json(400, {'error': 'question exceeds the length limit'})
                return
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._json(400, {'error': 'invalid content length'})
                return
            if length <= 0 or length > max_bytes:
                self._json(400, {'error': 'PDF body missing or exceeds the size limit'})
                return
            data = self.rfile.read(length)
            try:
                result = answer_func(data, question)
            except ImportError:
                self._json(500, {'error': 'missing optional dependency'})
                return
            except (DocumentError, ValueError, OSError, RuntimeError) as exc:
                # Type name only; do not leak paths or internals to the page.
                self._json(422, {'error': type(exc).__name__})
                return
            self._json(200, result)

        def log_message(self, *args):
            pass

    return Handler


def make_server(port, answer_func, host='127.0.0.1', max_bytes=MAX_PDF_BYTES):
    if host not in LOOPBACK_HOSTS:
        raise ValueError('refusing to bind outside loopback')
    return ThreadingHTTPServer((host, port), make_handler(answer_func, max_bytes))


def main():
    parser = argparse.ArgumentParser(description='Loopback-only web UI for cited PDF answers. Trusted local inputs; do not expose to a network.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument('--cache-dir')
    parser.add_argument('--offline', action='store_true', help='Use downloaded model files only')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be from 1 to 65535')
    try:
        threshold = check_min_score(args.min_score)
    except ValueError as exc:
        parser.error(str(exc))

    def answer_func(data, question):
        return answer_bytes(data, question, min_score=threshold,
                            cache_dir=args.cache_dir, offline=args.offline)

    server = make_server(args.port, answer_func)
    host, port = server.server_address[:2]
    print(f'Serving on http://{host}:{port} (loopback only). Ctrl+C to stop.',
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
