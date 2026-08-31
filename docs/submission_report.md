# Track 4 Submission Report

## Executive Summary

The shopping copilot combines a deterministic conversational retriever with an optional, offline Gemini semantic-enrichment pipeline. The submitted default path is network-free, standard-library-only, reproducible, and reports zero model tokens. It reaches a public-set TechnicalScore of `0.970050` while retaining Hit Rate@10 of `1.0`. All numbers below are measured on the 200 released sessions; no hidden-set result is claimed.

## Public Evaluation Evidence

| Metric | Overall | Boundary | Browsing | Buying | Intent Override |
|---|---:|---:|---:|---:|---:|
| Sample count | 200 | 10 | 80 | 80 | 30 |
| Hit Rate@10 | 1.000000 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |
| MRR | 0.967500 | 0.933333 | 0.960417 | 0.975000 | 0.977778 |
| MTTC | 2.010000 | 2.500000 | 1.825000 | 1.500000 | 3.700000 |

Overall efficiency is `0.899`; recommended TechnicalScore is `0.970050`; reported prompt, completion, and total tokens are all zero.

## Architecture and Technical Execution (35%)

```text
turn -> parser -> isolated state -> category pool -> evidence ranking -> breadth gate -> response
                                         ^              |
                                         |              +-> clarification
                          validated semantic cache
                          (optional; weakest signal)
```

The parser resolves the published buying, browsing, disclosure, override, deferral, and exhaustion forms. State is keyed by `session_id`; an override replaces only the tracked initial preference. Catalog indexing derives normalized category aliases and canonical signatures from structured features/details plus material, color, and price signals. Ranking prioritizes canonical equality, literal phrases, token coverage, optional cached semantic overlap, quality, and stable order. No constraint hard-filters candidates.

Recommendation breadth is confidence-gated: fewer than four active constraints returns the best candidate while still asking an open question; four constraints or exhaustion widens to `top_k`. This increases first-rank precision without sacrificing catalog-valid output or Hit Rate@10.

The optional Gemini layer is genuine AI engineering but is deliberately outside the live turn path. An explicit builder produces allowlisted semantic tags; cached tags can only break deterministic evidence ties. `Agent.reset()` and `Agent.respond()` cannot call the network.

## Innovation and Problem Insight (20%)

The central insight is that the benchmark rewards both retrieval and rank position, while a shopper with sparse intent should not be flooded with weak alternatives. The system therefore pairs recommendations with clarification and adapts breadth to accumulated evidence. It treats intent override as selective state repair rather than a session reset.

The AI layer addresses a different weakness—sparse or paraphrased catalog language—through offline semantic metadata. This hybrid avoids turning a reliable retrieval problem into a latency- and quota-dependent chat completion problem.

### Ablation evidence

| Stage | Hit Rate@10 | MRR | MTTC | TechnicalScore | Interpretation |
|---|---:|---:|---:|---:|---|
| Released weak baseline | 0.125000 | 0.068034 | 9.810000 | 0.106710 | Weak lexical starter |
| Deterministic state + catalog evidence | 1.000000 | 0.712728 | 1.525000 | 0.903318 | Coverage and reliability |
| Confidence-gated breadth | 1.000000 | 0.967500 | 2.010000 | 0.970050 | Better first-rank precision; modest turn trade-off |

Gemini cached mode is not included as a score-improving ablation because no generated cache result is claimed.

## Impact and Relevance (20%)

- Shoppers receive a strong option immediately and retain control through explicit clarification and override.
- Retailers can deploy against an existing catalog without a vector database, online model dependency, or fabricated identifiers.
- Platform operators get deterministic fallback, bounded output, auditable state, and optional incremental semantic enrichment.
- The approach is relevant where reliability, privacy, and cost matter more than unconstrained conversational fluency.

Deployment can begin with the default deterministic mode, add a scheduled offline enrichment job using a dedicated unbilled project, validate the cache in staging, and enable cached tie-breaking only after quality checks. Provider loss never blocks shopping turns.

## Feasibility and Practicality (15%)

The default requires Python 3.10+ and the standard library. A captured Windows 11/Python 3.12.13 public run completed in `14.156` seconds including catalog initialization and evaluation. Default model/API cost is zero.

Gemini build limits are hard-clamped to 8 products/request, 10 requests/run, 20 requests/rolling 24 hours, a 30-second minimum interval, 6,000 serialized request characters, 512 output tokens, 20-second timeout, sequential execution, and one counted retry. A dedicated project with billing disabled prevents accidental paid use. Provider quotas and model availability remain account-specific and can change, so free-tier availability is not guaranteed; correctness does not depend on it.

Privacy controls exclude shopper/session/evaluator data and catalog identifiers, redact URLs, send only truncated public product fields, authenticate by header, validate a strict response schema, and store only normalized tags plus aggregate accounting. Locks, atomic writes, content/catalog fingerprints, checkpoints, and rolling-window timestamps make partial builds safe and resumable.

## Presentation and Communication (10%)

The companion [demo script](demo_script.md) demonstrates a complete multi-turn session, override behavior, benchmark evidence, and network-free AI architecture in three minutes. The [final checklist](final_submission_checklist.md) distinguishes verified repository evidence from external team obligations.

## Reproduction

```powershell
python -m unittest discover -s tests -v
python -m compileall starter evaluator tests tools
python -m evaluator.local_evaluator
python tools/run_evidence.py
```

Retain ignored `results.json` and `evidence_manifest.json` with the frozen submitted commit. The evidence runner invokes the evaluator as a subprocess and records aggregate metrics only; it does not modify evaluator code or preserve per-session labels.

## Limitations and Responsible AI

- Public templates and lexical overlap may not represent organic language; public performance does not guarantee final performance.
- The four-constraint breadth threshold is an interpretable heuristic, not a calibrated probability.
- Cached tags can be wrong; they never filter candidates, introduce ASINs, or outrank source catalog evidence.
- Unpaid Gemini inputs may be retained or reviewed under provider terms. Only minimized public catalog snippets are eligible; shopper data is prohibited.
- The anonymized profile is not used for learned personalization, avoiding unsupported inference but limiting personalization value.
- No license, individual contribution names, release URL, public demo URL, or hidden result is asserted here; the team must supply those externally.

## Contributions

Repository work is separated by role: product reasoning/specification, implementation/testing, evaluation/evidence, and documentation/demo. The Devpost roster and team submission must provide authoritative individual names and contribution attribution.

## Governing Documents

- [Submission rules](submission_rules.md)
- [Final evaluation FAQ](final_evaluation_faq.md)
- [Competition specification](competition_specification.md)
- [Agent API contract](agent_api_contract.json)
