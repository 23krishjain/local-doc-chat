# Day 4: actual local text embeddings

## Built
An in-memory cosine-similarity index over page-preserving text chunks. The CLI
returns source hash, physical page, character offsets and text for each nearest
match. It does not generate an answer. Default chunks are 500 characters with
75 overlap; no chunk crosses a page. Empty/no-text pages are reported, not OCRed.

## Model run, not just a stub
FastEmbed 0.9.1 ran the all-MiniLM-L6-v2 ONNX text embedding model on CPU. Outputs
are 384-dimensional. This is a small text encoder, not Qwen's vision/chat model.
Real embedding inference succeeded, including cache-only mode after download.
The ONNX artifact is Qdrant/all-MiniLM-L6-v2-onnx; upstream metadata checked on
18 Nov lists Apache-2.0, revision d13954661f83248295ba75c1ed411eef3b7b936e.
The runtime downloads by model name/cache rather than a revision lock, so exact
future reproducibility requires preserving/checking model artifacts separately.
No model weights are committed to this repo.

On the included two-page synthetic policy, 6 of 6 prewritten answerable
questions retrieved the expected page at rank 1. Two absent-answer queries also
returned nearest pages, as expected from a nearest-neighbour search. Scores for
the absent queries were 0.098 and 0.290. These are not confidence probabilities,
not a calibrated refusal threshold, and not evidence of general accuracy.
Only two candidate pages make this an easy smoke test. Full cases, result data
and a runnable evaluation are in eval/. No generated-answer accuracy was tested.

## Decisions
- Small ONNX CPU encoder avoids requiring a GPU just for retrieval. Explicit
  model install/download is still needed on first use; --offline uses cache only.
- No vector database until data volume needs one. Linear scan is O(chunks*dim).
  CLI rejects more than 2000 chunks. Index is rebuilt per invocation, not saved.
- Normalise vectors and verify count, dimensions and finite nonzero values.
- Reject inputs over the model's 256-token limit using a separate untruncated
  tokenizer, rather than silently embedding only a prefix. Character chunks
  alone do not ensure a token bound, especially outside English.
- Preserve page/offset provenance. A page match is evidence to inspect, not a
  correct answer. Do not pretend retrieval abstains when evidence is absent.

## Checks and open gaps
51 unit/parser/render tests pass; nine new retrieval tests use controlled vectors
to check ranking and error paths. The separate evaluation uses the actual model.
Vision inference, answer generation, scanned-page embeddings/OCR and end-to-end
PDF Q&A remain unverified/unimplemented. English short text is this encoder's
target; non-English and complex layouts need separate evaluation.

Trusted local PDFs only. Existing parser resource/isolation limits still apply.
JSON stdout contains document text; don't log or commit private documents.

## Interview questions
1. Why does normalisation turn a dot product into cosine similarity?
2. Why is top-1 page recall different from answer accuracy?
3. Why will nearest-neighbour retrieval return something for an absent answer?
4. Why can 500 characters exceed a 256-token model budget?
5. When is a vector database worth its additional moving parts?

Sources:
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://huggingface.co/Qdrant/all-MiniLM-L6-v2-onnx
- https://qdrant.github.io/fastembed/
