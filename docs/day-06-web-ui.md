# Day 6: a loopback-only web UI, with the same honesty rules

## Built
`python -m docchat.web` serves a minimal page on 127.0.0.1. The browser posts
raw PDF bytes plus a question to the same process (`POST /ask?q=...`) and gets
the Day 5 result as JSON: an exact cited passage, or `insufficient_evidence`
with below-threshold evidence labelled. The pipeline is literally shared:
`docchat.answer.answer_bytes` now backs both the CLI and the server, so the web
path cannot drift from the tested path.

## Model run over HTTP
Real all-MiniLM-L6-v2 CPU encoder, cache-only, exercised through the socket:
the refund question answered with the page-2 citation, the absent CEO question
abstained with both nearest chunks labelled below threshold, and a corrupt
upload returned a clean `{"error": "DocumentError"}` with no internals. Server
started and stopped cleanly.

## Decisions
- Stdlib `http.server` only. No framework dependency to audit or expire, and
  the HTTP layer is small enough to test fully.
- Raw body + query parameter instead of multipart forms: Python's `cgi` module
  is deprecated/removed in newer versions, and the fetch API makes multipart
  unnecessary here. Chunked transfer is not accepted; Content-Length is
  required and bounded (20MiB, same as the CLI).
- Refuses to bind anything but loopback (0.0.0.0 raises). No auth/TLS: this is
  a single-user local tool for trusted inputs, not a server to expose; the
  README says so next to the command.
- Error responses carry the exception type name only, never paths or message
  internals. Request logging is silenced to keep the terminal usable.
- Stateless: the index is rebuilt per question (capped at 2000 chunks). Slower
  for large documents, correct by construction. Caching is a later decision,
  not a hidden one.
- The embedding model loads lazily on the first question, per process.

## Checks and open gaps
73 tests pass: eight new HTTP tests drive a real socket against a stub pipeline
(routing, 404s, size caps, loopback refusal, error shape) and three cover the
shared byte pipeline; none call a model. The page markup was parsed and checked
from served bytes; the layout was not pixel-rendered in this environment.
Still open: no generated answers, vision/chat inference unverified, scan-only
pages invisible to the text index, single document per index, threshold
fixture-tuned.

## Interview notes
- Why not Flask/FastAPI? For one endpoint, a framework adds supply-chain and
  version risk without changing the user-visible result; the point of the day
  is the trust boundary (loopback, bounded input, no internal leaks), which is
  framework-independent.
- What would exposing this on a network require? Authentication, TLS, request
  rate limits, sandboxed PDF parsing, resource limits per request, and a
  rethink of trusted-input assumptions - which is why the code refuses
  non-loopback binds instead of relying on a comment.
- Why rebuild the index per request? It keeps every answer tied to the exact
  bytes just uploaded; a cache keyed by content hash is safe to add later, a
  cache keyed by filename is not.
