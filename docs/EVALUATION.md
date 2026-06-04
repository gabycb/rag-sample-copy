# Evaluation & Content Safety

How to measure and gate the quality and safety of ATLAS-RAG, following Azure AI
Foundry Evaluation SDK best practices. The runnable harness lives in
[`eval/evaluate.py`](../eval/evaluate.py); the runtime input guard is
[`src/bot/content_safety.py`](../src/bot/content_safety.py).

## Why evaluate

A RAG system can fail in ways unit tests never catch: it can hallucinate beyond the
retrieved context, retrieve the wrong (or, worse, unauthorized) documents, or be
steered by injected instructions. Treat evaluation as a **CI gate**, not a one-off.

## The golden dataset

Curate a versioned dataset of representative `{query, context, response,
ground_truth}` rows (see [`eval/dataset.sample.jsonl`](../eval/dataset.sample.jsonl)).
Include:

- common real questions per audience (engineering, sales, HR, …),
- known-hard / ambiguous queries,
- **negative cases** — questions whose answer the user is *not* authorized to see
  (validates security trimming end to end), and
- **adversarial cases** — direct and indirect prompt-injection attempts.

Grow it from production logs (with PII scrubbed) and every regression you fix.

## Metrics (Azure AI Foundry Evaluation SDK)

Quality (`azure-ai-evaluation`, LLM-judge on a 1–5 scale):

| Evaluator | What it catches |
|---|---|
| `GroundednessEvaluator` | Answer claims not supported by retrieved context (hallucination) |
| `RelevanceEvaluator` | Answer doesn't address the question |
| `RetrievalEvaluator` | Retrieved chunks are off-topic / poorly ranked |
| `ResponseCompletenessEvaluator` | Answer omits required information |
| `CoherenceEvaluator` / `FluencyEvaluator` | Readability of the response |

Safety (require an Azure AI project; judged by the safety service):

| Evaluator | What it catches |
|---|---|
| `IndirectAttackEvaluator` | **Indirect prompt injection** via retrieved documents (top risk here) |
| `ContentSafetyEvaluator` | Violence / Sexual / SelfHarm / HateUnfairness |
| `ProtectedMaterialEvaluator` | Regurgitated copyrighted material |

## Suggested thresholds & gate

Start here and tighten over time (mirrored in `eval/evaluate.py`):

- Groundedness ≥ 4.0, Relevance ≥ 3.0, Retrieval ≥ 3.0 (mean over the dataset).
- Zero tolerance on safety: any `IndirectAttack` / high-severity content-safety hit fails the build.

```bash
# Offline smoke test (no Azure) — wire this into CI as a fast pre-check:
python eval/evaluate.py --dry-run

# Full run against the golden dataset (needs AZURE_AI_PROJECT_ENDPOINT + judge model):
pip install -r eval/requirements.txt
python eval/evaluate.py --dataset eval/dataset.sample.jsonl
```

`evaluate.py` exits non-zero when a threshold is missed, so it fails the pipeline.

## Runtime content safety (defense in depth)

Offline evals catch regressions; the runtime guard stops live attacks. Because
retrieved SharePoint content is attacker-influenceable, **indirect** prompt injection
is a first-class risk. `content_safety.py` calls Azure AI Content Safety
**Prompt Shields** (`text:shieldPrompt`) on both the user prompt and the retrieved
documents *before* generation, and fails closed. Enable it with
`ENABLE_CONTENT_SAFETY=true` and `AZURE_CONTENT_SAFETY_ENDPOINT=...`.

Groundedness is enforced as an offline gate (above) rather than per-request, to avoid
adding judge-model latency to every turn.

## Recommended cadence

- **Per PR (CI):** `--dry-run` smoke test + the offline unit tests.
- **Nightly / pre-release:** full evaluator run against the golden dataset; block release on regressions.
- **Continuously:** sample production traffic into the dataset; alert on Application Insights safety/latency metrics.
