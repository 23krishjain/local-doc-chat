# Day 8 - Library-aware web UI

Date: 2026-11-22

## What was built

`docchat/web.py` gained a library mode (`--library STORE`). The loopback-only
web UI now serves the Day 7 persistent multi-document library:

- `GET /` serves a library page: file picker + "Add to library", a live
  document list (SHA-256 prefix, pages, chunks, no-text pages), and an ask box.
- `POST /library/add` adds raw PDF bytes to the library; unchanged documents
  reuse their validated cache instead of re-embedding.
- `GET /documents` returns the document list as JSON.
- `POST /library/ask?q=...&k=...` answers across every stored document with
  the Day 5 evidence gate; citations name the owning document by content hash.
  `k` is validated to 1..20; blank and overlong questions are rejected.
- Single-upload `/ask` is not served in library mode; the modes are distinct.
- Library operations are serialized with a lock: the shared embedder and the
  cache files are not thread-safe.

Single-upload mode (Day 6 behavior) is unchanged; existing tests pass as-is.

## Verification

- 13 new HTTP tests with a library-shaped stub (no model, no filesystem):
  page served, add + list roundtrip, ask roundtrip with k, blank/bad-k/
  oversize rejections, error responses leaking exception type names only,
  corrupt-cache list failure, single-upload route 404 in library mode,
  loopback-only binding, handler/library required. Suite: 98/98.
- Real CPU MiniLM offline eval over HTTP (`eval/web_library_check.py`,
  results in `eval/day08-results.json`): policy added and embedded, re-add
  reused the cache (`embedded: false`), scanned receipt added with 0 chunks
  and page 1 flagged no-text, both documents listed, cross-document ask
  answered with a page 2 citation bound to the policy SHA-256 (score 0.461),
  absent question abstained with below-threshold nearest evidence only.
- Pixel-level visual check in headless Chrome against the running server:
  document-list state, answered state and insufficient-evidence state all
  rendered as intended.

## Honest limits

- Answers on the page are raw JSON (the Day 6 caveat); the document list is
  rendered text. A formatted citation view is future work, not claimed here.
- Still loopback-only with no authentication or TLS; trusted local inputs.
- The 0.34 evidence threshold remains fixture-tuned, not calibrated.
- Scan-only PDFs still contribute no text chunks; OCR is not built.
- Library mode serializes requests; no concurrency hardening.
- Vision/chat model inference remains unverified; nothing here claims it.

## Interview questions

1. Why serialize library operations with a lock instead of making the
   embedder and cache layer thread-safe? What would real thread safety cost?
2. What breaks if two `docchat.web --library` processes share one store
   directory? How would you detect or prevent it?
3. Why does `GET /documents` return metadata only (no chunk text)? What is
   the privacy argument given the cache files contain extracted text?
4. Design a remove-document flow for this UI. What confirmation and error
   semantics would you choose, and why is it currently CLI-only?
5. The page renders raw JSON answers. Sketch the smallest citation-rendering
   change that would make answers readable, and name one XSS mistake a naive
   version could make.
