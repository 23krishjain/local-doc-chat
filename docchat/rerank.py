"""Second-stage reranking of retrieved candidates with a cross-encoder.

A cross-encoder reads the question and one passage together, so it is slower than
the first-stage vectors but usually orders a short candidate list better. The
scorer is injectable so the ordering logic is testable without a model.
"""
import math

MODEL = 'Xenova/ms-marco-MiniLM-L-6-v2'  # Apache-2.0, runs on CPU via ONNX


class CrossEncoder:
    """fastembed cross-encoder. Downloads the model on first use, like the embedder."""
    model_name = MODEL

    def __init__(self, cache_dir=None, offline=False):
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        self.model = TextCrossEncoder(MODEL, cache_dir=cache_dir, threads=2, local_files_only=offline)

    def scores(self, query, passages):
        return [float(s) for s in self.model.rerank(query, list(passages))]


def rerank(query, candidates, scorer, *, top=None):
    """Reorder candidate indexes by scorer(query, passages) -> one score each.

    candidates: list of (index, passage_text). Returns indexes best first; ties keep
    first-stage order. Scores are model-specific relevance logits, not probabilities.
    """
    if not candidates:
        return []
    if top is not None and (type(top) is not int or top < 1):
        raise ValueError('top must be a positive integer')
    scores = list(scorer(query, [text for _, text in candidates]))
    if len(scores) != len(candidates):
        raise ValueError('scorer must return one score per candidate')
    if not all(isinstance(s, (int, float)) and math.isfinite(s) for s in scores):
        raise ValueError('scores must be finite numbers')
    order = sorted(range(len(candidates)), key=lambda p: (-scores[p], p))
    result = [candidates[p][0] for p in order]
    return result[:top] if top else result
