# Day 5: cited extractive answers, and saying "I don't have that"

## Built
`python -m docchat.answer` answers from PDF evidence or abstains. When the top
retrieved match clears a minimum cosine score it returns the exact passage with
citations (physical page, character offsets, score, source SHA-256). When
nothing clears the threshold it returns `insufficient_evidence` and shows the
nearest passages explicitly labelled below threshold. Day 4's open gap - two
absent-answer questions returning irrelevant pages presented as results - is
now gated on this fixture.

## Model run, measured gate behaviour
Same real CPU all-MiniLM-L6-v2 ONNX encoder as Day 4, rerun cache-only. On the
included two-page synthetic policy: 6/6 answerable questions answered with the
expected page as primary citation; 2/2 absent-answer questions abstained. Full
data in eval/day05-results.json; rerun with eval/abstention_check.py.

Honesty limits, unchanged from Day 4: the default threshold 0.34 was chosen to
separate these 8 prewritten questions (lowest answerable 0.364, highest absent
0.290; margin under 0.05 on one side). It is not calibrated confidence, not a
probability, and not transferable to other documents or models without
retuning. Two candidate chunks make this easy. No generated-answer quality was
measured; the excerpt is a quote, not a synthesis.

## Decisions
- Extractive only. The answer payload's excerpt is byte-identical to a
  retrieved chunk; nothing paraphrases or generates, so there is nothing to
  hallucinate between retrieval and response.
- Citations are constructed only from retrieved Match records plus the hash of
  the bytes actually parsed, then re-validated against the retrieved set before
  output. Tampered page/offsets/text/score/hash or a foreign passage fail
  validation (unit-tested). This is the boundary a future chat model's
  citations will have to satisfy.
- Abstention still shows nearest evidence, labelled below_threshold, so a
  refusal is inspectable rather than a bare "no".
- Threshold is a named, overridable CLI option with validation, not a hidden
  constant. Single threshold only; no margin rule added without data to tune it.

## Checks and open gaps
62 unit/parser/render/retrieval/gate tests pass; the eleven new ones use stub
matches and never call a model. The real-model gate eval is separate
(eval/abstention_check.py). Open: chat/vision model inference still unverified;
no upload UI; scan-only pages still invisible to the text index; threshold
needs retuning per real corpus; no multi-document indexing yet.

## Interview notes
- Why threshold-gate instead of always answering? Nearest-neighbour retrieval
  always returns something; without a gate, unanswerable questions get
  confident-looking irrelevant evidence, which is worse than a refusal.
- Why extractive before generative? Citations can be validated exactly against
  retrieval output, so the honesty boundary is testable today; a generator's
  faithfulness needs a separate evaluation we have not built.
- What breaks this gate? A corpus where relevant and irrelevant scores overlap;
  the threshold is empirical per corpus/model, which is why the eval is
  committed and the limit is stated next to every result.
