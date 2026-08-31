# Three-Minute Demo Script

## 0:00–0:25 — Problem and Result

Open the README and state: the copilot must recommend from 50,000 catalog products while clarifying incomplete intent and surviving intent changes. Show the public result: Hit Rate@10 `1.0`, MRR `0.9675`, TechnicalScore `0.97005`, zero runtime tokens. Say explicitly that this is the 200-session public set, not the hidden final set.

## 0:25–1:20 — Complete Multi-Turn Session

Run an Agent session or show an evaluator trace:

1. Shopper asks broadly for a product category. Point out that the agent returns one best candidate and an `other` clarification rather than flooding the shopper.
2. Add two constraint disclosures. Show isolated state accumulating catalog-grounded evidence.
3. Issue “Actually, ignore my earlier preference…” and show only the replaceable preference changes while unrelated constraints remain.
4. Add enough evidence to reach four active constraints, or exhaust preferences, and show recommendations widen to `top_k`.

Emphasize that every returned ID comes from the frozen catalog and recommendations appear on every turn.

## 1:20–2:05 — Architecture and AI Engineering

Show the README architecture flow. Explain deterministic evidence order: canonical signature, literal phrase, token coverage, optional semantic tags, quality, stable order.

Then open `starter/semantic_enrichment.py` and explain:

- Gemini runs only from an explicit offline builder; the Agent has no live model call.
- Requests contain opaque indices and truncated catalog snippets—never shoppers, sessions, evaluator labels, or ASINs.
- Hard caps enforce 8 products/request, 10 requests/run, 20/day, 2 RPM, 512 output tokens, sequential execution, and one retry.
- Structured validation, fingerprints, checkpoints, atomic writes, and deterministic fallback handle failure.

Do not make a live API call during the demo; tests provide deterministic evidence without consuming quota.

## 2:05–2:35 — Reproducibility

Run:

```powershell
python -m unittest discover -s tests -v
python tools/run_evidence.py
```

Open the ignored evidence manifest and point to commit hash, clean tracked state, catalog SHA-256, platform/Python, duration, command, aggregate metrics, and zero tokens. Note that per-session labels and secrets are excluded.

## 2:35–3:00 — Impact, Trade-Off, Close

Summarize the deployment path: start deterministic at zero API cost; optionally build semantic tags offline; enable only validated cached tie-breaking. Name the trade-off honestly: MRR improved substantially while MTTC rose from `1.525` to `2.01`. Close with reliable shopper control, incremental AI value, and provider-independent correctness.

## Judge Q&A Prompts

- Why not call Gemini on every turn? Network latency, quota, privacy, and reproducibility would become correctness dependencies.
- Can hallucinated tags produce products? No; tags cannot create IDs or alter the candidate pool.
- Is free tier guaranteed? No. Local hard caps and an unbilled project constrain spend; availability is provider/account-specific.
- What remains before submission? Use the external-action section of the final checklist.
