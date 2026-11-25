# Day 10: hybrid retrieval and a retrieval eval

- Added BM25, rank fusion and `method=` on `Index.search`. 14 new tests: BM25
  term weighting, saturation, length normalisation, hand-computed RRF, ranker
  and Index behaviour with a fake embedder. Full suite: 139 tests.
- Eval chunk size is 300 characters because 500-character chunks of
  math-heavy papers exceeded MiniLM's 256-token limit and were rejected by the
  existing guard. The library still uses 500; adopting 300 is a separate change.
- Result: hybrid best MRR (0.350 vs 0.281 dense, 0.319 BM25); BM25 best
  recall@10 (0.677). No claim beyond this 31-question set.

Next: vector index (ANN) against brute force with measured recall/latency,
reranking, then grounded generation.
