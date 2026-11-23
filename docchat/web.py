"""Loopback-only web UI over the cited-answer pipeline.

Trusted local inputs on a single-user machine. Binds 127.0.0.1/::1 only; it is
not hardened for network exposure, authentication or hostile PDFs. No uploads
leave the machine: the browser posts raw PDF bytes to this same process.

Two modes:
- single-upload (default): each POST /ask carries one PDF's bytes and a
  question; the index is rebuilt per request.
- library (--library STORE): PDFs are added once to the persistent
  content-addressed library, then questions run across every stored document
  with per-document citations. Library operations are serialized with a lock
  because the shared embedder and cache files are not thread-safe.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys
import threading
from urllib.parse import urlparse, parse_qs

from .answer import DEFAULT_MIN_SCORE, answer_bytes, check_min_score
from .library import Library
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

LIBRARY_PAGE = b"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>local-doc-chat library</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font-family:system-ui,sans-serif;max-width:46rem;margin:2rem auto;padding:0 1rem}
input[type=text]{width:100%;box-sizing:border-box;padding:.4rem}
pre{background:#f4f4f4;padding:1rem;white-space:pre-wrap;border:1px solid #ddd}</style></head>
<body>
<h1>local-doc-chat library</h1>
<p>Add PDFs once, then ask across the whole library. The answer is an exact
passage with page citations naming the document by its SHA-256, or
<em>insufficient evidence</em>. Everything runs on this machine; no upload
leaves your computer.</p>
<p><input type="file" id="file" accept="application/pdf">
<button id="add">Add to library</button></p>
<h2>Documents</h2>
<pre id="docs" aria-live="polite">Loading...</pre>
<h2>Ask the library</h2>
<p><input type="text" id="q" maxlength="2000" placeholder="Question across all documents"></p>
<button id="ask">Ask</button>
<pre id="out" aria-live="polite"></pre>
<script>
async function refreshDocs() {
  const docs = document.getElementById('docs');
  try {
    const r = await fetch('/documents');
    const data = await r.json();
    if (!r.ok) { docs.textContent = 'Could not list documents: ' + data.error; return; }
    if (!data.documents || !data.documents.length) {
      docs.textContent = 'Library is empty. Add a PDF above.';
      return;
    }
    docs.textContent = data.documents.map(d =>
      d.source_sha256.slice(0, 12) + '...  pages=' + d.pages +
      '  chunks=' + d.chunks +
      (d.no_text_pages.length ? '  no-text pages=' + d.no_text_pages.join(',') : '')
    ).join('\\n');
  } catch (e) { docs.textContent = 'Could not load documents: ' + e; }
}
document.getElementById('add').addEventListener('click', async () => {
  const out = document.getElementById('out');
  const f = document.getElementById('file').files[0];
  if (!f) { out.textContent = 'Choose a PDF first.'; return; }
  out.textContent = 'Adding (first add loads the local model)...';
  try {
    const r = await fetch('/library/add', {method: 'POST', body: f});
    const data = await r.json();
    out.textContent = JSON.stringify(data, null, 2);
    refreshDocs();
  } catch (e) { out.textContent = 'Request failed: ' + e; }
});
document.getElementById('ask').addEventListener('click', async () => {
  const out = document.getElementById('out');
  const q = document.getElementById('q').value;
  if (!q.trim()) { out.textContent = 'Type a question.'; return; }
  out.textContent = 'Working...';
  try {
    const r = await fetch('/library/ask?q=' + encodeURIComponent(q), {method: 'POST'});
    const data = await r.json();
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) { out.textContent = 'Request failed: ' + e; }
});
refreshDocs();
</script>
</body></html>"""


# Use DOM text nodes, never interpolate document text into HTML.
RESULT_SCRIPT = b"""
function renderResult(data) {
  const out = document.getElementById('out');
  out.replaceChildren();
  const line = (tag, value) => {
    const node = document.createElement(tag);
    node.textContent = value;
    out.appendChild(node);
  };
  if (data.error) {
    line('h3', 'Could not process this request');
    line('p', data.error + '. Check the file, local model cache and library.');
    return;
  }
  if ('embedded' in data) {
    line('h3', data.embedded ? 'Document added' : 'Document already indexed');
    line('p', data.chunks + ' text chunks from ' + data.pages + ' pages.');
    line('p', 'Document SHA-256: ' + data.source_sha256);
    if (data.ocr_pages && data.ocr_pages.length)
      line('p', 'OCR attempted on pages ' + data.ocr_pages.join(', ') + '. Check recognition against the original.');
    if (data.no_text_pages && data.no_text_pages.length)
      line('p', 'No text on pages ' + data.no_text_pages.join(', ') + '. Try library mode with --ocr for scans.');
    return;
  }
  if (data.status === 'insufficient_evidence') {
    line('h3', 'Insufficient evidence');
    line('p', 'No passage cleared the evidence threshold. Try a more specific question or add the right document.');
    return;
  }
  line('h3', 'Source passage');
  line('blockquote', data.excerpt || '');
  line('h3', 'Page citations');
  for (const c of data.citations || []) {
    line('p', 'Page ' + c.page + ' | characters ' + c.start + '-' + c.end +
      ' | similarity ' + c.score.toFixed(3));
    line('p', 'Document SHA-256: ' + c.source_sha256);
  }
  line('p', 'Exact retrieved text, not a generated answer. Similarity is not confidence. OCR text may be wrong.');
}
"""
for _name in ('PAGE', 'LIBRARY_PAGE'):
    _page = globals()[_name].replace(b'<pre id="out" aria-live="polite"></pre>',
                                    b'<section id="out" aria-live="polite"></section>')
    _page = _page.replace(b'<script>', b'<script>' + RESULT_SCRIPT, 1)
    _page = _page.replace(b'out.textContent = JSON.stringify(data, null, 2);',
                          b'renderResult(data);')
    _page = _page.replace(b'</style>', b' #out{overflow-wrap:anywhere} blockquote{white-space:pre-wrap;margin:1rem 0;padding:1rem;background:#f0f5fa;border-left:4px solid #246} button{padding:.5rem .8rem;cursor:pointer} pre{overflow-wrap:anywhere}</style>')
    globals()[_name] = _page


def make_handler(answer_func=None, library=None, max_bytes=MAX_PDF_BYTES,
                 min_score=DEFAULT_MIN_SCORE):
    if answer_func is None and library is None:
        raise ValueError('make_handler needs an answer_func or a library')
    lib_mode = library is not None
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = 'docchat-local/0'

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _page(self, content):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _bounded_body(self):
            """Request body within the cap, or None after a 400 was sent."""
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                self._json(400, {'error': 'invalid content length'})
                return None
            if length <= 0 or length > max_bytes:
                self._json(400, {'error': 'PDF body missing or exceeds the size limit'})
                return None
            return self.rfile.read(length)

        def _question(self, params):
            """Validated question text, or None after a 400 was sent."""
            question = params.get('q', [''])[0]
            if len(question) > MAX_QUESTION_CHARS:
                self._json(400, {'error': 'question exceeds the length limit'})
                return None
            return question

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/':
                self._page(LIBRARY_PAGE if lib_mode else PAGE)
            elif lib_mode and path == '/documents':
                try:
                    with lock:
                        docs = library.documents()
                except (DocumentError, OSError, RuntimeError) as exc:
                    self._json(422, {'error': type(exc).__name__})
                    return
                self._json(200, {'documents': docs})
            else:
                self._json(404, {'error': 'not found'})

        def do_POST(self):
            parsed = urlparse(self.path)
            path, params = parsed.path, parse_qs(parsed.query)
            if not lib_mode and path == '/ask':
                question = self._question(params)
                if question is None:
                    return
                data = self._bounded_body()
                if data is None:
                    return
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
            elif lib_mode and path == '/library/add':
                data = self._bounded_body()
                if data is None:
                    return
                try:
                    with lock:
                        meta = library.add_bytes(data)
                except ImportError:
                    self._json(500, {'error': 'missing optional dependency'})
                    return
                except (DocumentError, ValueError, OSError, RuntimeError) as exc:
                    self._json(422, {'error': type(exc).__name__})
                    return
                self._json(200, meta)
            elif lib_mode and path == '/library/ask':
                question = self._question(params)
                if question is None:
                    return
                if not question.strip():
                    self._json(400, {'error': 'question must not be blank'})
                    return
                try:
                    k = int(params.get('k', ['3'])[0])
                except ValueError:
                    self._json(400, {'error': 'k must be an integer from 1 to 20'})
                    return
                if not 1 <= k <= 20:
                    self._json(400, {'error': 'k must be an integer from 1 to 20'})
                    return
                try:
                    with lock:
                        result = library.ask(question, min_score=min_score, k=k)
                except ImportError:
                    self._json(500, {'error': 'missing optional dependency'})
                    return
                except (DocumentError, ValueError, OSError, RuntimeError) as exc:
                    self._json(422, {'error': type(exc).__name__})
                    return
                self._json(200, result)
            else:
                self._json(404, {'error': 'not found'})

        def log_message(self, *args):
            pass

    return Handler


def make_server(port, answer_func=None, host='127.0.0.1', max_bytes=MAX_PDF_BYTES,
                library=None, min_score=DEFAULT_MIN_SCORE):
    if host not in LOOPBACK_HOSTS:
        raise ValueError('refusing to bind outside loopback')
    return ThreadingHTTPServer(
        (host, port),
        make_handler(answer_func, library, max_bytes, min_score))


def main():
    parser = argparse.ArgumentParser(description='Loopback-only web UI for cited PDF answers. Trusted local inputs; do not expose to a network.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument('--cache-dir')
    parser.add_argument('--offline', action='store_true', help='Use downloaded model files only')
    parser.add_argument('--ocr', action='store_true', help='OCR textless pages in library mode with local Tesseract English')
    parser.add_argument('--library', metavar='STORE',
                        help='Serve the persistent multi-document library at STORE instead of single-upload mode')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be from 1 to 65535')
    try:
        threshold = check_min_score(args.min_score)
    except ValueError as exc:
        parser.error(str(exc))

    if args.library:
        library = Library(args.library, cache_dir=args.cache_dir,
                          offline=args.offline, ocr=args.ocr)
        server = make_server(args.port, library=library, min_score=threshold)
    else:
        def answer_func(data, question):
            return answer_bytes(data, question, min_score=threshold,
                                cache_dir=args.cache_dir, offline=args.offline, ocr=args.ocr)
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
