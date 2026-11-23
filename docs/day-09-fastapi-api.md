# Day 9 - FastAPI JSON API over the library

Date: 2026-11-23

Routed by the hiring work: current backend JDs (GetCrux, Gridbricks and other
Python roles) call for HTTP API validation and error-handling evidence, so
today's slice adds a real FastAPI service on top of the existing pipeline
instead of the planned OCR. OCR stays queued, not abandoned.

## What was built

`docchat/api.py`: a FastAPI app factory (`create_app(library, min_score,
max_bytes)`) over the Day 7 content-addressed library:

- `GET /health` liveness.
- `GET /documents` lists the library (hash, pages, chunks, no-text pages).
- `POST /documents` adds raw PDF bytes (20MiB cap, 400 on missing/oversize
  body) and returns the add metadata, including whether the validated cache
  was reused. 201 on success.
- `POST /ask` takes a validated JSON body: `question` 1-2000 characters and
  non-blank, `k` 1-20, default 3. Returns the same evidence-gated cited
  answer as the CLI/web UI, with citations bound to the owning document hash.
- Declarative validation via pydantic; 422 responses list field locations and
  constraint kinds, never the submitted values.
- Pipeline failures (DocumentError/ValueError/OSError/RuntimeError) map to
  422 carrying the exception type name only; ImportError maps to 500 with a
  generic dependency message.
- Docs UI and OpenAPI schema are disabled; the API is the contract.
- Loopback-only bind in `main` (other hosts refused), no auth/TLS, same
  trusted-local-input boundary as the rest of the project. Library operations
  serialized with a lock.

## Verification

- 13 new tests with a library-shaped stub (`tests/test_api.py`, httpx
  TestClient, no model, no filesystem): health, docs disabled, add/list/ask
  roundtrips, missing/oversize bodies, every validation failure mode, no
  input echo in validation details, pipeline error type-only mapping,
  dependency 500, min-score validation. Suite: 111/111.
- Real offline MiniLM eval through the ASGI app (`eval/api_check.py`,
  `eval/day09-results.json`): policy embedded once, cache reused on re-add,
  scanned receipt 0 chunks + no-text page 1, both documents listed, cross-doc
  ask answered with a page 2 citation bound to the policy SHA-256, absent
  question abstained.
- Live uvicorn socket smoke test: `/health`, a real cited answer (page 2,
  score 0.461), blank question 422, document listing over loopback TCP.

## Honest limits

- This is HTTP API design/validation/error-handling evidence over an existing
  retrieval service. It is not Django/Temporal experience and not deployed
  production hardening: no auth, TLS, rate limiting or multi-process safety.
- The pinned starlette (1.7.0) deprecates the httpx-based TestClient for
  `httpx2`; tests pass on the pinned set and the deprecation is disclosed.
- In-process TestClient evals plus one loopback socket smoke test; no
  load/performance measurement is claimed.
- Threshold still fixture-tuned; scan-only PDFs still contribute no chunks;
  vision/chat inference still unverified.

## Interview questions

1. Why return field locations and constraint kinds but never the submitted
   values in a 422? When could echoing input be a real vulnerability?
2. `POST /documents` takes raw bytes instead of multipart form data. What did
   that choice remove (dependency, parser surface), and what would multipart
   add that a browser upload flow needs?
3. The API serializes library operations with a lock. Walk through what
   corrupts without it: embedder state, cache file writes, or both?
4. Why disable the OpenAPI schema and docs UI here, and when would that be
   the wrong call for a team API?
5. How would you add per-client rate limiting to this service without
   breaking its single-user local trust model?
