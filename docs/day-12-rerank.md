# Day 12: cross-encoder reranking

- `docchat/rerank.py`: injectable-scorer `rerank()` plus a fastembed cross-encoder
  wrapper. 6 logic tests always run; 1 test uses the real model and runs only
  when `DOCCHAT_MODEL_CACHE` points at a cached model (it passed here).
- Eval: hybrid top 30 reranked. MRR 0.350 -> 0.380, recall@3 0.387 -> 0.484,
  recall@5 0.452 -> 0.581, recall@1 unchanged (0.226). 31 questions, author
  labelled, strict evidence-string relevance. Small differences are noise.
- Not done: no wiring into UI/API, no latency measurement for reranking, no
  second reranker model compared, no generation.

Next: grounded generation with the verbatim-quote check, or UI/API wiring.
