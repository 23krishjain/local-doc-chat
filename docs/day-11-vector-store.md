# Day 11: SQLite vector store with exact and HNSW backends

- `VectorStore`: unit-length float32 vectors in SQLite, exact numpy or FAISS HNSW
  search behind one `search()`. 17 tests (HNSW tests skip without faiss).
- Measured on 10,155 chunks of 29 public arXiv papers: HNSW recall@10 0.9993
  against exact, 0.20 ms vs 0.99 ms median. Exact is already fast at this size,
  so the honest conclusion is that the index is a correct, tested option, not
  a needed speedup yet.
- Not done: no incremental HNSW insert (full rebuild), no filtering by document
  inside the ANN search, no wiring into the web UI/API, no larger-scale test.
- Fixed the README test count (124 -> 156 after this change).

Next: reranker or grounded generation with the existing quote check.
