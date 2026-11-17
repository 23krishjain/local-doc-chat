# Day 3: page images, not imagined OCR

## Built
`python -m docchat.render` turns selected physical PDF pages into PNGs. A JSON
manifest links each image to a 1-based page and the SHA-256 of the exact source
bytes. Blank pages are not skipped or renumbered. Rendering does not call a
model, extract words from scans, or answer questions.

A synthetic image-only receipt has no extractable text but renders visibly with
a total of INR 180. A second check renders page 2 of the policy sample, retaining
its physical page 2 in the manifest. Both resulting PNGs were visually inspected.

## Decisions
- Use pypdfium2/PDFium for rendering, separate from pypdf's text extraction.
  pypdfium2's own license choices are Apache-2.0/BSD-3-Clause; PDFium and bundled
  dependencies have their own notices. No binary code or model weights are
  vendored here. Keep upstream wheel notices if redistributing binaries.
- Rendering is explicit, not automatically triggered by `no_text`: blank pages
  and unextractable text are not necessarily scans.
- Read one bounded snapshot so extraction, rendering and the hash use the same
  bytes. The extra snapshot is removed before publishing output.
- Preflight pixel dimensions before allocating the page bitmap. Defaults allow
  four million pixels per page and twenty million total. Render one page at a
  time and explicitly close page/bitmap/document handles.
- Write to a temporary sibling directory; ordinary failures remove partial work.
  Reject an existing output path rather than overwrite previous pages. This is
  a single-user local tool, not a concurrency-safe upload transaction service.

## Tests and limits
42 tests total: 29 previous and 13 new rendering/provenance checks. Rendering
checks use the actual PDFium backend, including pixels, white blank pages,
page selection, invalid selection, encryption, corruption, byte/pixel budgets
and cleanup after failure. No model inference has been performed.

Pixel budgets are not a native-code parser sandbox or execution-time bound.
Text validation still parses the full document, including unselected pages.
Use trusted local files only. An exposed upload service needs isolated workers,
hard CPU/memory/time limits and hostile-PDF tests first. Very small print may
be unreadable at the chosen DPI; increasing it uses more memory and may exceed
budgets. PDFs/images and manifests written locally may contain private data.
Do not commit private renders; use synthetic samples only.

## Interview questions
1. What does a source hash prove, and what does it not prove about a citation?
2. Why is rendering an image different from understanding it?
3. Why check pixel counts before render rather than file size afterward?
4. What can still exhaust memory despite pixel and byte limits?
5. How would concurrent jobs affect this simple directory-output design?

Sources:
- https://pypdfium2.readthedocs.io/en/stable/python_api.html
- https://pypdfium2.readthedocs.io/en/stable/readme.html
