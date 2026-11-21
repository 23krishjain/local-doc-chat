# Day 7: many documents, one library, provenance by content hash

## Built
`python -m docchat.library` manages a local multi-document library: add PDFs,
list them, ask questions across all of them, remove by hash. Documents are
named by the SHA-256 of their exact bytes, so the same file under two names is
one document and a changed file is a new one. Answers keep Day 5's contract -
exact cited passage or `insufficient_evidence` - but every citation is now
bound to its owning document's hash, not just a page.

## Model run, measured
Real all-MiniLM-L6-v2 CPU encoder, cache-only, on the two synthetic samples:
the policy PDF embedded once and was reused (not re-embedded) on re-add; the
scanned receipt contributed zero text chunks with its no-text page reported;
the refund question answered with the policy's hash at page 2 across the
two-document library; the absent CEO question abstained. Full data in
eval/day07-results.json, reproducible via eval/library_check.py. Two tiny
documents prove plumbing and provenance, not general accuracy; the threshold
remains fixture-tuned.

## Decisions
- Content addressing, not filenames. Identity is the document's bytes; a rename
  changes nothing, an edit produces a new identity. Cache filenames are
  validated as 64-hex before any filesystem use, and removal rejects anything
  else, so ids cannot traverse paths.
- The cache is a cache. On add, persisted vectors are trusted only when they
  reproduce the freshly parsed chunks (page/offsets/text) and the current model
  name exactly. Model upgrades or parser changes silently misaligning vectors
  with text is the failure this rules out. Mismatch, corruption, wrong version:
  re-embed. Reading the library is fail-loud instead: a corrupt cache file
  raises with a re-add instruction rather than silently dropping a document
  from answers.
- Lazy embedding. Loading the library never touches the model; only new
  documents and new questions do. Query embedding still needs the model even
  when every document vector is cached - that is the one thing a cache cannot
  precompute.
- Merged index is capped at 5000 chunks total; per-document caps still apply.
  The store is a directory of JSON files written atomically (temp + replace),
  not a database; simultaneous writers are out of scope and documented.
- Cache files contain extracted document text. They inherit the documents'
  privacy: store directory stays local and git-ignored patterns cover the
  default layout.

## Checks and open gaps
85 tests pass; the twelve new ones use stub embedders and fixture PDFs, no
model. Covered: cache reuse, cross-instance load without a model, per-document
citation binding, corrupt/tampered/model-mismatched cache handling, chunk caps,
hash-validated removal, empty-library abstention. Open: the web UI still
handles one document per request (library-aware UI is a natural next step);
no OCR for scan-only pages; chat/vision model inference still unverified;
threshold still needs per-corpus tuning; no incremental re-chunk of edited
documents (an edit is a new document by design).

## Interview notes
- Why content addressing? It makes dedup, cache validation and citation
  provenance the same mechanism: one hash answers "have I seen this?", "can I
  trust these vectors?" and "which document did this quote come from?".
- What is the cache invalidation rule? There is none to forget: the cache entry
  must reproduce a fresh parse byte-for-byte in text and offsets, so stale
  entries lose on comparison instead of needing invalidation logic.
- Why fail loud on corrupt cache at read time? Silently skipping a document
  makes answers incomplete without saying so; a visible error with a repair
  path keeps the library's answers complete or clearly unavailable.
