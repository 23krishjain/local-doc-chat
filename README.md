# local-doc-chat

A local image and document Q&A project, built one step at a time.
The goal is to answer from uploaded PDFs/images, with page references. Today
single-image Q&A through a local Ollama server and text-PDF extraction with
page-linked chunks are implemented. No document retrieval, PDF Q&A, OCR, web
upload UI or multi-turn memory yet.

## Current status (Day 2)

The image HTTP client/CLI and text-PDF reader/chunker are implemented.
29 tests pass: 11 image HTTP-fixture checks and 18 PDF/chunking checks.
No test calls a real model. **Actual vision inference, answer quality and
hardware performance have not been verified.** No benchmark results are claimed.

## Try it locally

Python 3.10+; the client itself has no third-party dependencies.
Install Ollama using its official instructions: https://ollama.com/download .
Run its local server, then in another terminal:

```sh
ollama pull qwen2.5vl:7b
python -m docchat samples/receipt.png 'What is the total on this receipt?'
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

Scanned-page rendering; retrieval over
chunks; grounded Q&A with source pages; a small evaluation set including absent
answers; then a local upload/chat interface. Page citations are evidence to
inspect, not proof the answer is true. Tests and daily notes live in `tests/`
and `docs/`. Actual model evaluation remains an open requirement.

## Sources

- Ollama model tags/sizes: https://ollama.com/library/qwen2.5vl
- Chat request contract: https://docs.ollama.com/api/chat
- Official 7B model: https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct
- Official 3B license: https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct/raw/main/LICENSE

Project code is MIT licensed. Model/runtime licenses are separate.
