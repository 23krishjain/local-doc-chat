# Day 2: PDF pages before answers

## Built
Text extraction using pypdf, with a record for every physical page (1-based).
A separate chunker splits extracted text without crossing pages and keeps
character offsets. `python -m docchat.pdf` prints pages/chunks as JSON. Added
18 checks on real generated PDFs and the chunker, for 29 passing tests total.

## Decisions
- Keep blank/no-text pages instead of dropping them and accidentally shifting
  source references. `no_text` is deliberately not named `scanned`: a parser
  cannot infer that from an empty result alone.
- Use fixed character windows with overlap for a first retrieval input. Their
  limits are obvious: they can split words and are not a token budget. Retrieval
  quality will need evaluation; smaller pieces are not automatically better.
- Reject encrypted PDFs instead of asking for passwords or silently unlocking.
- Pin pypdf 7.1.0 and test that exact version in a clean virtual environment.
  No network/model calls happen during parsing or tests.
- Default bounds cover file bytes, page count and extracted characters, but are
  not a hostile-file sandbox. Compressed streams may expand before checks run.
  An exposed upload UI will need isolation and hard time/memory limits first.

## Evidence and limits
The included two-page sample is synthetic. Page 1 says standard delivery costs
INR 40; page 2 says refund requests must be made within 7 days. Tests extract
real PDF text, retain a middle blank page, reject encryption/corruption, mark an
image-only page no_text, and verify chunk offsets and CLI failures. These are
parser tests, not an LLM accuracy score. No OCR, retrieval or PDF answers yet.
Multi-column reading order, tables and unusual fonts remain unverified.

Real model inference remains open from Day 1. Nothing in this work proves
Qwen2.5-VL fits or runs well on the target laptop. PDF processing can proceed
without pretending the missing model evaluation happened.

## Interview questions
1. Why is a physical page number different from the printed page label?
2. Why can no extracted text mean more than a scanned page?
3. What does overlap buy, and what duplicate evidence can it create?
4. Why is a compressed file-size limit not a memory bound?
5. How would you test whether chunking improves answer retrieval?

Parser guidance: https://pypdf.readthedocs.io/en/stable/user/extract-text.html
