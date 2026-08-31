# Track 4 Submission Report

## Solution

The agent is a deterministic, standard-library-only conversational catalog retriever. It parses the evaluator's customer-facing message forms into a coarse category and constraint phrases, keeps state per `session_id`, and applies intent overrides by replacing only the tracked initial preference while preserving unrelated disclosed constraints. Products are indexed locally from the frozen catalog. Each product receives an immutable canonical signature containing all normalized feature entries, all detail `key: value` entries, the first detected material and color signals, and a price-derived budget signal. Category aliases form the initial candidate pool; signature agreement is ranked before additive normalized phrase/token evidence, with rating count, rating, and stable catalog order as deterministic tie-breakers. Every response returns catalog-valid, deduplicated recommendations and an open clarification while information may remain.

This design deliberately has no runtime LLM, API, network, or external dependency. It reports zero prompt, completion, and total tokens and incurs zero model/API cost. Unexpected parsing or ranking failures degrade to a deterministic category/global-quality response.

## Public Evaluation Evidence

The unmodified local evaluator produced the following final public-set measurements:

| Metric | Overall | Boundary | Browsing | Buying | Intent Override |
|---|---:|---:|---:|---:|---:|
| Sample count | 200 | 10 | 80 | 80 | 30 |
| Hit Rate@10 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| MRR | 0.712728 | 0.601944 | 0.640799 | 0.723695 | 0.912222 |
| MTTC | 1.525000 | 1.500000 | 1.212500 | 1.062500 | 3.600000 |

Overall efficiency was `0.9475` and recommended TechnicalScore was `0.903318`. Reported prompt, completion, and total tokens were all zero. These are public-set measurements only; no hidden-set performance is claimed.

## Reproduction and Runtime

From the repository root, with the released catalog at `data/catalog.jsonl`:

```powershell
python -m unittest discover -s tests -v
python -m compileall starter evaluator tests
python -m evaluator.local_evaluator
```

An independent measured evaluator run took 13.776 seconds on Windows NT 10.0.26200.0, Python 3.12.13, AMD64 Family 25 Model 33, with 12 logical processors. There were 305 total evaluated `respond` calls, giving approximately 45 ms amortized end-to-end wall time per call including initialization. This is not an isolated inference-latency benchmark and is environment-dependent. The generated `results.json`, commit hash, timestamp, and environment details should be retained together as run evidence; generated output is intentionally ignored by git.

## Limitations

The approach is partly tuned to the released evaluator's stable customer-message templates and benefits from lexical overlap with catalog metadata. Unseen paraphrases or sparse metadata can lower recall. The anonymized profile is not yet used for learned personalization, and the system has no dense semantic retrieval layer. Public-set performance does not guarantee final-set performance. Future work would add an offline semantic index, broader paraphrase handling, and profile-aware ranking while retaining deterministic fallbacks.

## Contributions

Repository contributions are attributed by role: implementation (agent and tests), evaluation (benchmark execution and metric verification), and documentation (reproduction, disclosures, and report). The Devpost team roster is authoritative for individual names, team membership, and administrative contribution details.

## Governing Documents

- [Submission rules](submission_rules.md)
- [Final evaluation FAQ](final_evaluation_faq.md)
- [Competition specification](competition_specification.md)
- [Agent API contract](agent_api_contract.json)
