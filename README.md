# TechJam Conversational Shopping Copilot

This submission implements the Track 4 conversational shopping agent. It asks an open clarification question while information may remain, maintains isolated per-session state, and returns ranked catalog recommendations on every turn.

## What You Receive

- A frozen catalog of 50,000 products from the `Clothing_Shoes_and_Jewelry` category of Amazon Reviews 2023.
- 200 labeled public sessions for local development.
- A deterministic conversational agent and local evaluator.
- The Agent API contract and scoring rules.

The organizer keeps 800 additional sessions unreleased until the Devpost submission deadline. After the deadline, the final evaluation package will be released and teams will run the unmodified official evaluator in their own environments using their frozen submitted commit.

See [`docs/final_evaluation_faq.md`](docs/final_evaluation_faq.md) for the final evaluation, network, credentials, hardware, data, and scoring policy.

## Task

For each session, your agent receives an anonymized preference profile and a short customer message. Raw user IDs, review text, timestamps, and purchase history are never disclosed. On every turn the agent may:

- ask a natural clarification question in `message` and identify one requested field in `ask_attribute`;
- return a ranked list of up to 10 catalog `parent_asin` values;
- do both in the same response.

The session ends when the target product appears in the scored Top 10 or after turn 10. Sessions cover Buying, Browsing, Intent Override, and Boundary behavior.

## Download the Catalog

Download `catalog.jsonl.gz` from the GitHub Release attached to this repository, then run:

```bash
gzip -dk catalog.jsonl.gz
mv catalog.jsonl data/catalog.jsonl
```

Verify the downloaded file using the published `SHA256SUMS` file.

## Setup and Reproduction

Python 3.10 or later is required. The submission uses only the Python standard library.

```bash
python -m evaluator.local_evaluator
```

The repository targets Python 3.12.13 on the measured run and uses only the Python standard library; no package installation is required. Place the released catalog at `data/catalog.jsonl` (50,000 rows). From the repository root, run:

```powershell
python -m unittest discover -s tests -v
python -m compileall starter evaluator tests
python -m evaluator.local_evaluator
```

The evaluator is unmodified and writes aggregate and per-session output to `results.json` (ignored by git). Retain that file with the frozen commit hash and execution details for submission evidence. To record the commit associated with a run:

```powershell
git rev-parse HEAD
Get-Date
```

The default-off agent scored Hit Rate@10 `1.0`, MRR `0.9675`, MTTC `2.01`, efficiency `0.899`, and recommended TechnicalScore `0.97005` on the 200-session public set. The weak BM25 baseline scored `0.106710`; see `docs/baseline_results.json`. These are public-set results only, not a claim about the unreleased final set.

## Agent Interface

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict) -> None:
        ...

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return {
            "message": "Do you have a material preference?",
            "ask_attribute": "material",
            "recommendations": [
                {"parent_asin": "B000..."},
                {"parent_asin": "B001..."}
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30}
        }
```

`ask_attribute` is one of `category`, `material`, `color`, `size`, `style`, `brand`, `budget`, `feature`, `use_case`, `other`, or `null`. See `docs/agent_api_contract.json`.

## Technical Metrics

- **Hit Rate@10:** fraction of sessions that find the target within 10 turns.
- **MRR:** mean reciprocal rank of the target; a miss contributes zero.
- **MTTC:** mean first-hit turn; a miss is assigned turn 11.
- **Reported token usage:** prompt and completion tokens returned by the team's model client.

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

`TechnicalScore` is an objective input to the `Technical Execution` assessment. It is not a separate judging criterion and does not represent the entire `Technical Execution` score.

Only exact `parent_asin` equality produces a hit. Core metrics are also reported by scenario.

## Architecture and Runtime Disclosure

The default runtime is deterministic and uses no model endpoint or network access. It has no third-party dependencies, reports zero prompt/completion/total tokens, and has zero model/API cost. It parses documented message forms, isolates session state, preserves unrelated constraints during intent overrides, and indexes canonical catalog evidence. Ranking orders canonical equality, literal phrase/coverage, optional cached semantic overlap, quality, then stable catalog order. While evidence is sparse it returns one best result plus clarification; after four active constraints or exhaustion it widens to `top_k`.

```text
message + session state
          |
          v
template parser -> category aliases -> candidate pool
          |                              |
          v                              v
active constraints ---------> deterministic evidence ranking
                                      |
optional validated tag cache ---------+  (weakest evidence; no network)
                                      |
                                      v
                    confidence-gated recommendations + clarification
```

An optional offline semantic-enrichment utility is included in `starter/semantic_enrichment.py`. It is default-off, never called from `Agent.reset()` or `Agent.respond()`, and uses only a minimized catalog projection. Explicit `build` operation requires `GEMINI_API_KEY` and writes a validated content-addressed cache; runtime evaluation remains network-free. The builder is hard-clamped to batches of 8, 10 requests/run, 20 requests/rolling day, 30 seconds between requests, 6,000 prompt characters, 512 output tokens, 20-second timeout, and one counted retry. Provider failures preserve completed cache state and do not affect deterministic behavior. Example (operator-invoked only):

```powershell
$env:GEMINI_API_KEY = "..."
python -m starter.semantic_enrichment --catalog data/catalog.jsonl --cache data/semantic_cache.json
```

Do not send identifiers, shopper/session data, conversations, evaluator data, credentials, or raw responses to the provider. Free-tier prompts may be retained or reviewed by the provider; use a dedicated unbilled project and review provider terms before building a cache.

Supported environment variables are exactly `GEMINI_API_KEY` (CLI build authentication), `SHOPPING_ENRICHMENT_MODE` (`off` by default or `cached` for validated local tags), and `SHOPPING_ENRICHMENT_CACHE` (optional cache path, default `data/semantic_cache.json`). The generated cache path is git-ignored. No other runtime configuration variables are read.

The latest captured public run took `14.156` seconds on Windows 11 and Python 3.12.13, including catalog initialization and the full evaluator. Runtime varies by hardware and filesystem. Generate a fresh commit-bound manifest after the final commit:

```powershell
python tools/run_evidence.py
```

Retain the ignored `evidence_manifest.json` and `results.json` with the frozen commit hash. The manifest records aggregate metrics, catalog SHA-256/size, UTC timestamp, platform, Python version, duration, command, commit, and tracked-worktree state; it excludes per-session labels and environment secrets.

## Limitations and Reflection

The retrieval strategy intentionally uses the released evaluator's documented message forms and benefits from catalog lexical overlap. Unseen paraphrases, sparse metadata, and the heuristic four-constraint confidence threshold can reduce quality; the anonymized profile is not used for learned personalization. Cached Gemini tags are optional, unbenchmarked semantic tie-breakers—not a hidden-set claim—and unpaid-provider data handling may change. The implementation does not claim performance on the unreleased final set.

Repository contributions are attributed by role: implementation covers the agent and tests; evaluation covers benchmark execution and metric verification; documentation covers reproducibility and submission disclosures. The Devpost roster is authoritative for individual names, team membership, and administrative attribution.

## Files

```text
data/public_set.jsonl             200 labeled development sessions
docs/competition_specification.md participant rules and evaluation protocol
docs/final_evaluation_faq.md      final evaluation and judging clarifications
docs/agent_api_contract.json      machine-readable Agent contract
docs/evaluation_config.json       scoring configuration
docs/baseline_results.json        reproducible weak-starter reference score
starter/agent.py                  deterministic conversational agent
evaluator/local_evaluator.py      public-set simulator and scorer
docs/submission_report.md         method, evidence, and limitations report
docs/demo_script.md               three-minute multi-turn demonstration plan
docs/final_submission_checklist.md repository and external freeze checklist
tools/run_evidence.py             sanitized reproducibility manifest runner
```

## Judging and Submission Policy

- [Participant submission requirements](docs/submission_rules.md)
- [Final evaluation FAQ](docs/final_evaluation_faq.md)
- [Submission report](docs/submission_report.md)
- [Demo script](docs/demo_script.md)
- [Final submission checklist](docs/final_submission_checklist.md)

## Data Source

The catalog and sessions are derived from Amazon Reviews 2023 by McAuley Lab, UCSD. See `DATA_ATTRIBUTION.md` before using or redistributing the data.
Sessions are sampled deterministically from the official Clothing 5-core leave-last-out split and joined to the frozen catalog.
