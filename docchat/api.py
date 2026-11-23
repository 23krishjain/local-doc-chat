"""FastAPI JSON API over the content-addressed library pipeline.

Structured validation and error mapping on top of the same Day 5/Day 7
pipeline the CLI and stdlib UI use. Trust boundary is unchanged: this is for a
local or otherwise trusted deployment, binds loopback by default, ships no
authentication or TLS, and error responses carry the exception type name only,
never paths or internals. Library operations are serialized with a lock; the
shared embedder and cache files are not thread-safe.

Run with: python -m docchat.api --library .docchat-library [--port 8000]
"""
import argparse
import sys
import threading

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ConfigDict, field_validator

from .answer import DEFAULT_MIN_SCORE, check_min_score
from .library import Library
from .pdf import DocumentError

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_QUESTION_CHARS = 2000
LOOPBACK_HOSTS = {'127.0.0.1', '::1', 'localhost'}


class AskRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    k: int = Field(default=3, ge=1, le=20)

    @field_validator('question')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('question must not be blank')
        return value


def create_app(library, min_score=DEFAULT_MIN_SCORE, max_bytes=MAX_PDF_BYTES):
    """ASGI app over one library instance. The caller owns the library."""
    threshold = check_min_score(min_score)
    lock = threading.Lock()
    app = FastAPI(title='local-doc-chat API', version='0.1.0',
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        # Field names and constraint kinds only, never echoed input values.
        errors = [{'loc': [str(part) for part in e.get('loc', [])],
                   'type': e.get('type', 'invalid')}
                  for e in exc.errors()]
        return JSONResponse({'error': 'validation', 'detail': errors},
                            status_code=422)

    @app.exception_handler(DocumentError)
    @app.exception_handler(ValueError)
    @app.exception_handler(OSError)
    @app.exception_handler(RuntimeError)
    async def pipeline_handler(request, exc):
        return JSONResponse({'error': type(exc).__name__}, status_code=422)

    @app.exception_handler(ImportError)
    async def dependency_handler(request, exc):
        return JSONResponse({'error': 'missing optional dependency'},
                            status_code=500)

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/documents')
    def documents():
        with lock:
            return {'documents': library.documents()}

    @app.post('/documents', status_code=201)
    async def add_document(request: Request):
        try:
            length = int(request.headers.get('content-length') or 0)
        except ValueError:
            return JSONResponse({'error': 'invalid content length'},
                                status_code=400)
        if length <= 0 or length > max_bytes:
            return JSONResponse(
                {'error': 'PDF body missing or exceeds the size limit'},
                status_code=400)
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > max_bytes:
                return JSONResponse({'error': 'PDF exceeds the size limit'},
                                    status_code=400)
            data.extend(chunk)
        if len(data) != length:
            return JSONResponse({'error': 'content length mismatch'}, status_code=400)
        def add():
            with lock:
                return library.add_bytes(bytes(data))
        meta = await run_in_threadpool(add)
        return JSONResponse(meta, status_code=201)

    @app.post('/ask')
    def ask(payload: AskRequest):
        with lock:
            return library.ask(payload.question, min_score=threshold,
                               k=payload.k)

    return app


def main():
    parser = argparse.ArgumentParser(description='FastAPI JSON API for the local-doc-chat library. Trusted local inputs; do not expose to a network.')
    parser.add_argument('--library', required=True, metavar='STORE',
                        help='Persistent library store directory')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--min-score', type=float, default=DEFAULT_MIN_SCORE)
    parser.add_argument('--cache-dir')
    parser.add_argument('--ocr', action='store_true', help='OCR textless pages with local Tesseract English')
    parser.add_argument('--offline', action='store_true',
                        help='Use downloaded model files only')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be from 1 to 65535')
    if args.host not in LOOPBACK_HOSTS:
        parser.error('refusing to bind outside loopback')
    try:
        threshold = check_min_score(args.min_score)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        import uvicorn
    except ImportError:
        print('uvicorn is required: pip install -r requirements-api.txt',
              file=sys.stderr)
        return 1
    library = Library(args.library, cache_dir=args.cache_dir,
                      offline=args.offline, ocr=args.ocr)
    app = create_app(library, min_score=threshold)
    uvicorn.run(app, host=args.host, port=args.port, log_level='warning')
    return 0


if __name__ == '__main__':
    sys.exit(main())
