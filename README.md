# local-doc-chat

A local, single-user PDF evidence-Q&A tool. Add text PDFs or scanned printed
English PDFs, ask across a persistent document library, and read exact source
passages with physical page numbers and document SHA-256 citations. Includes
a browser UI, command-line tools and a FastAPI JSON API.

## Release scope

The **local PDF/scan evidence-Q&A portfolio release is implemented**. It uses
real CPU MiniLM embeddings and opt-in local Tesseract OCR. Answers are retrieved
quotes, not LLM-generated explanations. If the top similarity does not clear
the evidence threshold, the tool returns insufficient evidence.

The separate Ollama image client is experimental: its protocol tests pass,
but actual vision/chat inference and laptop GPU performance have **not** been
verified. This release does not claim a finished generative vision chatbot.
No public deployment, authentication, TLS, multi-user operation or production
hardening is included. Only use trusted local documents.

## Quick start

Python 3.10+. Create a virtual environment and install the full dependency set:

```sh
python -m venv .venv
# Linux/macOS:
. .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-all.txt
```

For scan OCR, separately install Tesseract with English language data and put
`tesseract` on PATH. On Debian/Ubuntu:

```sh
sudo apt-get install tesseract-ocr tesseract-ocr-eng
tesseract --version
```

Other platform instructions: https://tesseract-ocr.github.io/tessdoc/Installation.html
OCR was tested here with Tesseract 4.1.1, English data. Other versions and
platforms have not been tested in this project. Without it, omit `--ocr` and
use text-layer PDFs.

```sh
python -m docchat.web --library .docchat-library --ocr --cache-dir .cache/fastembed
```

Open **http://127.0.0.1:8765** on the same computer. Add
`samples/policy.pdf` and `samples/scanned-receipt.pdf`. Try:

- "What is the refund window for fees?" Expected: source passage on page 2,
  including the seven-day refund window.
- "What is the total on the receipt?" Expected: scanned receipt page 1,
  including `TOTAL: INR 180` after OCR.
- "What is the warranty period for the lunar module?" Expected: insufficient
  evidence on these fixtures.

The first embedding operation downloads the English MiniLM ONNX model
(about 90MB according to the runtime registry). Model download requests leave
the machine; document text is embedded locally, not sent to hosted inference.
For subsequent cache-only operation, use the same `--cache-dir` and add
`--offline`. Missing cached model files fail rather than silently use a cloud
service. Model weights are external and not committed.

The UI displays readable passages, citations, OCR warnings, missing-evidence
states and processing errors. Documents are shown by content-hash prefix,
not filename. Citations contain full hashes and character offsets. Removing
stored documents is available through the CLI, not a browser control.

## CLI and API

```sh
python -m docchat.library add .docchat-library samples/policy.pdf samples/scanned-receipt.pdf --ocr --cache-dir .cache/fastembed
python -m docchat.library list .docchat-library
python -m docchat.library ask .docchat-library 'What is the total on the receipt?' --offline --cache-dir .cache/fastembed
python -m docchat.library remove .docchat-library FULL_DOCUMENT_SHA256
python -m docchat.api --library .docchat-library --ocr --offline --cache-dir .cache/fastembed
```

API on `127.0.0.1:8000`:

| Method | Path | Input/result |
| --- | --- | --- |
| GET | `/health` | Liveness only, not model readiness |
| GET | `/documents` | Hashes, page/chunk counts, no-text/OCR page metadata |
| POST | `/documents` | Raw PDF bytes and correct Content-Length; 201 add metadata |
| POST | `/ask` | JSON question (1-2000 nonblank chars), strict integer k (1-20, default 3) |

```sh
curl -X POST http://127.0.0.1:8000/documents --data-binary @samples/policy.pdf
curl -X POST http://127.0.0.1:8000/ask -H 'Content-Type: application/json' -d '{"question":"What is the refund window for fees?","k":3}'
```

Validation errors return 422 with field locations and constraint kinds, not
echoed submitted values. Pipeline errors return 422 with exception type only;
missing dependencies return 500. Missing/oversize/mismatched upload lengths
return 400. Actual streamed bytes are capped before full buffering, even when
a claimed Content-Length is too small. Blocking add work runs off the ASGI
event loop; library operations remain serialized by a shared process lock.
Docs/OpenAPI are disabled. No throughput claim follows from these choices.

Without `--library`, `python -m docchat.web` runs the earlier stateless,
single-upload UI. It does not use OCR. The lower-level `docchat.pdf`,
`docchat.render`, `docchat.search` and `docchat.answer` modules remain usable;
see the development notes for their narrower contracts.

## Architecture and provenance

```text
PDF bytes -> bounded text extraction -> optional OCR of textless pages
          -> physical-page chunks -> local MiniLM embeddings
          -> per-document JSON vector cache -> cosine retrieval
          -> evidence gate -> exact quote + page/offset/hash citations
```

- Documents are identified by SHA-256 of their bytes, never filenames.
- Re-adding compares current extraction/model/mode with stored chunks before
  reusing vectors. Changed extraction is re-embedded. OCR re-add still renders
  and recognizes the textless pages to validate that match.
- A restart loads cached vectors without embedding documents again. Cache
  files are trusted local state, not signed or safe against a malicious local
  writer. Corrupt caches fail loudly; re-add the original document to repair.
- Cache files contain extracted/OCR text and vectors, not the original PDFs.
  Protect and back up the directory like the documents. `.docchat-*/` is
  git-ignored. Do not commit private caches, model files or generated output.
- Citations bind to retrieved passages and their owning document hash. OCR
  offsets refer to recognized text, not image coordinates. Page numbers are
  physical 1-based PDF pages, which may differ from printed page labels.
- Quote fidelity and provenance do not prove the quote answers the question
  or that its contents are true. Open the original and check it.

## Verification

```sh
python -m unittest discover -s tests -v
# equivalently, after installation: make test
# After a first model download, the release acceptance check is offline:
python eval/release_check.py --cache-dir .cache/fastembed
```

The full suite has **124 tests**, including real PDF extraction/rendering,
HTTP/ASGI validation, malformed-cache handling, citation binding, and an actual
English receipt OCR test when Tesseract is installed. Most retrieval/HTTP
unit tests use stub embeddings; they do not establish model accuracy. CI
example in `docs/ci/tests.yml.example` installs the English OCR engine and runs the suite; it is a template, not an active workflow or a claim of a remote CI pass.

`eval/release-results.json` records a separate real OCR + CPU embedding
acceptance check through the API: text PDF and scan upload, receipt total/page/
hash citation, policy citation after restart, absent-question abstention,
invalid-upload rejection, cache reuse and OCR metadata. The five earlier
`eval/*_check.py` checks remain regression tests with their saved results.
Only two synthetic PDFs are used. The earlier 6/6 page hits and 2/2 abstentions
are fixture results, not general accuracy, calibrated confidence or load tests.

Browser UI checks use real Chrome at desktop and phone widths, including
OCR upload, cited answer, insufficient evidence, error handling and inert
rendering of HTML-like document text. The UI uses text nodes, never document
HTML. Evidence images and notes: `docs/release.md`.

## Limits and safety

- Trusted local files only. Byte/page/character/pixel limits are guardrails,
  **not a hostile-PDF sandbox**. Native parsing can consume resources before
  checks. Do not expose either server or Ollama to the network.
- Loopback defaults and CLI bind checks do not replace authentication or
  browser-origin protections. An imported ASGI app can be served elsewhere
  by its caller; do not do this without separate hardening.
- PDF cap 20MiB, 100 pages, one million combined characters; merged library
  cap 5000 chunks. English MiniLM input is limited to 256 tokens with an
  explicit rejection instead of silent truncation. Linear vector search.
- OCR is opt-in on textless pages only, maximum 10 pages per PDF, 150DPI,
  bounded render pixels, 30-second Tesseract timeout per page. Printed English
  only tested. Blank pages may be OCR-attempted; no-text is not scan detection.
  Mixed pages with some text and unrecognized images are not OCR-augmented.
  Handwriting, tables, columns, rotations and tiny print may be wrong.
- Default evidence threshold 0.34 is tuned to the tiny synthetic fixture,
  not transferable or calibrated. Similarity is not a probability. New
  corpora need their own evaluation and threshold selection.
- Single-process, single-user library only. A process-local lock does not
  protect multiple CLI/server writers. Do not share a store between writers.
- Pinned Starlette 1.7.0 warns that httpx TestClient is deprecated in favor of
  httpx2. Tests pass on the pinned environment; migration is not claimed.
- No generative PDF answers, multi-turn memory or laptop GPU benchmarks.
  The optional image CLI `python -m docchat samples/receipt.png 'What is the
  total?'` requires a separately installed, running local Ollama model and
  has not had real-model inference verified here.

## License and references

Project code: MIT. Dependencies, engines and model licenses are separate;
no weights, Tesseract binary or language data are redistributed here.

- Tesseract manual / Apache-2.0: https://tesseract-ocr.github.io/tessdoc/
- Tesseract license: https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/LICENSE
- MiniLM ONNX artifact: https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx
- Ollama API: https://docs.ollama.com/api/chat
- Optional Qwen 7B artifact: https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct

The optional Qwen 7B metadata lists Apache-2.0, while the 3B variant has a
research/noncommercial license. Do not substitute variants for business use
without checking the exact artifact. Download size is not VRAM/RAM use.
Development history and interview questions are in `docs/day-*.md`. Those
notes describe their original session, not the current release contract.

This bounded PDF/scan release ends the planned feature work. Future projects
are separate; missing production and generative capabilities are limitations,
not an unending feature queue.
