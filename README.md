# local-doc-chat

A local image and document Q&A project, built one step at a time.
The goal is to answer from uploaded PDFs/images, with page references. Today
single-image Q&A through a local Ollama server and text-PDF extraction with
page-linked chunks, PDF-to-PNG rendering, dense text retrieval, cited
evidence-gated extractive answers and a loopback-only web UI are implemented.
No generated PDF answers, OCR, public server or multi-turn memory yet.

## Current status (Day 6)

The image HTTP client/CLI, text-PDF reader/chunker, page renderer, dense text
retrieval, evidence-gated cited answers and a loopback-only web UI are
implemented. 73 tests pass: the prior 62 checks plus eight HTTP checks and
three pipeline-byte checks. Separate real CPU embedding evaluations retrieved
the expected page for 6/6 answerable questions and abstained on 2/2
absent-answer questions on a two-page synthetic sample, using a fixture-tuned
threshold. That is not general accuracy or calibrated confidence.
Unit tests do not call a model; the separate evaluations do. **Actual vision/chat inference, generated answer quality and
hardware performance have not been verified.** No benchmark results are claimed.

## Try it locally

Python 3.10+; the client itself has no third-party dependencies.
Install Ollama using its official instructions: https://ollama.com/download .
Run its local server, then in another terminal:

```sh
ollama pull qwen2.5vl:7b
python -m docchat samples/receipt.png 'What is the total on this receipt?'
```

Run the full test suite after installing rendering/PDF dependencies:

```sh
python -m pip install -r requirements-render.txt -r requirements-search.txt
python -m unittest discover -s tests -v
```

The sample is synthetic: total INR 180 (tea INR 80 + sandwich INR 100).
A real run should be checked against that expected answer, not assumed correct.
The CLI reports request wall time, including model loading when cold. Record
GPU model, OS, Ollama version, model tag, context size and cold/warm state before
comparing times. No result from a different machine proves laptop performance.

## Read a text PDF (Day 2)

Install the pinned PDF parser, then extract the included synthetic policy:

```sh
python -m pip install -r requirements.txt
python -m docchat.pdf samples/policy.pdf
python -m docchat.pdf samples/policy.pdf --chunk-size 500 --overlap 75
```

The command prints JSON to stdout without creating a stored copy. Each page has
its physical 1-based PDF page number, extracted text and `text`/`no_text` status.
Each chunk has the page number and exact character offsets within that extracted
page text. Printed page labels may differ. Chunks never cross pages; a blank
page is kept in the page list so later page references do not shift.

`no_text` does not prove a page is scanned: it can also be blank, use unsupported
text encodings, or contain only images. No OCR or vision call is made yet. A
successful text extraction is not a question-answering result. Tables, columns,
reading order and whitespace may be wrong; compare extracted text to the PDF.
Fixed character chunks can split words and do not account for model token limits.

Limits: 20MiB input, 100 pages, one million extracted characters. Encrypted PDFs
are rejected. A failed read prints an error and exits nonzero without partial
JSON. These limits are **not a security sandbox**: PDF parsing/decompression can
consume resources before page/character checks run. Only use trusted local PDFs
for now. An internet-facing upload service needs process isolation, time/memory
limits and broader hostile-file testing before deployment. Redirecting stdout
stores the full extracted document, so do not commit private output to Git.

Synthetic sample checks: delivery fee is INR 40 on physical page 1; refund window
is 7 days on page 2. `samples/policy.pdf` is not an actual business policy.

## Render PDF pages (Day 3)

Install optional rendering dependencies (PDFium/Pillow), then choose pages:

```sh
python -m pip install -r requirements-render.txt
python -m docchat.render samples/scanned-receipt.pdf rendered-scan --dpi 120
python -m docchat.render samples/policy.pdf rendered-policy --pages 2 --dpi 100
```

Output is a new directory with `page-0001.png`-style filenames and `manifest.json`.
The manifest records the exact input SHA-256, physical page number, DPI, image
dimensions and text status. The source PDF is not copied into the final output.
Existing output paths are refused; choose a different name for another run.
Do not run concurrent writers to the same output path.

You can pass a rendered PNG into the Day 1 image client:

```sh
python -m docchat rendered-scan/page-0001.png 'What is the total on this receipt?'
```

This last command needs an actual local Ollama model. **It has not been verified
against a real model.** Expected sample answer: INR 180. Rendering is verified;
recognising/answering from the image is a separate open check.

Defaults: DPI 120 (allowed 36-200), at most four million pixels per page and
twenty million total. Lower DPI or select fewer pages if the budget is exceeded.
These are bitmap guardrails, not parser isolation. Only trusted local files.
The reader validates/extracts every page before rendering selected pages, which
can be expensive. No OCR or automatic scan detection. Output images contain the
source content; keep private renders out of Git. pypdfium2 and PDFium dependency
licenses/notices are separate from this repo's MIT license. See day-03 notes.

## Search text evidence (Day 4)

```sh
python -m pip install -r requirements-search.txt
python -m docchat.search samples/policy.pdf 'How long do I have to ask for my money back?' --k 1
# After the first model download, use cache-only mode:
python -m docchat.search samples/policy.pdf 'What does shipping cost?' --offline
python eval/retrieval_check.py --offline
```

The small English all-MiniLM-L6-v2 ONNX encoder runs on CPU via FastEmbed; it is
not the Qwen vision model. First use downloads model files (about 90MB according
to FastEmbed's registry). Local document text is embedded on-device, not sent to
a hosted inference API. `--cache-dir PATH` selects storage; `--offline` refuses
network model loading and fails if needed files are missing. Weights are not
bundled. Both original model and ONNX artifact metadata list Apache-2.0.

Results are nearest evidence with page/character offsets, not an answer. Cosine
scores are not confidence probabilities. Even an unrelated question gets a
nearest page: there is no calibrated abstention yet. Scan-only PDFs return no
text matches; rendering alone does not add their content to the text index.
The encoder limit is 256 tokens; overlong chunks/queries are rejected, not
silently truncated. Use smaller chunks through the Python API if necessary.
Current CLI rebuilds an in-memory index each time, capped at 2000 chunks.

The real-model smoke test's 6/6 page hits are on only two synthetic pages. Two
absent-answer questions still return irrelevant nearest pages. See eval/ for
cases/results; no general retrieval or generated-answer accuracy is claimed.

## Cited answers or abstention (Day 5)

```sh
python -m docchat.answer samples/policy.pdf 'How long do I have to ask for my money back?'
python -m docchat.answer samples/policy.pdf "What is the CEO's birthday?" --offline
python eval/abstention_check.py --offline
```

`docchat.answer` returns the exact retrieved passage with page/character
citations and the source SHA-256 when the top match clears `--min-score`
(default 0.34); otherwise it abstains with `insufficient_evidence` and labels
the nearest passages as below threshold. It never invents text: the excerpt is
always the exact retrieved chunk, and citations are validated against the
retrieved set and source bytes before output. This is extractive evidence with
provenance, not a generated answer and not proof the passage is true.

The 0.34 default only separates the included 8-question, two-page synthetic
fixture (lowest answerable score 0.364, highest absent 0.290). Cosine scores
are not probabilities; retune per corpus and model before relying on any
threshold. The gate separates this sample, nothing more.

## Local web UI (Day 6)

```sh
python -m docchat.web --port 8765
# then open http://127.0.0.1:8765 in a browser on the same machine
```

Binds loopback only and refuses any other host. The page posts raw PDF bytes to
the same process (`POST /ask?q=...`) and shows the cited extractive answer or
`insufficient_evidence`. No authentication, TLS or network hardening: it is a
single-user local tool for trusted inputs, not a server to expose. The index is
rebuilt per question (stateless, capped at 2000 chunks), so large documents are
slow. Errors return the exception type only, not internals. The HTML is a
minimal fetch-driven form; markup was checked from served bytes, not
pixel-rendered.

## Model and hardware

Qwen2.5-VL-7B is the initial candidate, not a fit guarantee. Ollama lists a 6GB
download for 7B and 3.2GB for 3B. Download size is NOT total RAM/VRAM use: image
processing, context and the runtime need extra memory. A 6GB GPU may require
CPU offload. Keep context modest (the client uses 4096) and measure locally.
Do not assume the advertised maximum context fits your laptop.

License matters: the official 7B model metadata lists Apache-2.0, while the
3B model uses a Qwen Research License with non-commercial restrictions. Do not
silently substitute 3B for commercial/in-house business use. Check the exact
artifact's license before downloading/using it; this repo redistributes no weights.
A smaller permissively licensed alternative needs a separate evaluation.

## Local-only boundaries

The client talks only to a loopback HTTP origin, bypasses proxies, refuses
redirects, and sends base64 image bytes to your own Ollama. It does not save
uploads or chat history. Keep Ollama bound to loopback and do not expose its
port to your network. Review Ollama's own settings/logging separately; this
client is not a full privacy or security audit. Initial model installation
requires internet access. Use synthetic files first, not private bank records.

Input is limited to PNG/JPEG with basic signature checks and a 10MiB cap.
This is not a secure general-purpose upload parser. Model outputs are untrusted;
no tools or commands are executed. Instructions embedded in images are treated
as content by the prompt, but prompts do not guarantee injection resistance.
Handwriting, charts, tables and tiny print may be wrong or unreadable.

## Next steps

Grounded extractive Q&A with source pages, abstention and a local web UI are
in. Next: multi-document indexing with persistence, or generated answers
grounded in validated citations once a chat/vision model run is actually
verified. Page citations are evidence to inspect, not proof the answer is true.
Tests and daily notes live in `tests/` and `docs/`. Actual model evaluation
remains an open requirement.

## Sources

- Ollama model tags/sizes: https://ollama.com/library/qwen2.5vl
- Chat request contract: https://docs.ollama.com/api/chat
- Official 7B model: https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct
- Official 3B license: https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE

Project code is MIT licensed. Model/runtime licenses are separate.
