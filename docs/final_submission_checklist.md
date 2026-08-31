# Final Submission Checklist

## Verified in the Repository

- [x] Unmodified public evaluator command is documented.
- [x] Hit Rate@10 `1.0` and TechnicalScore `0.970050` reproduce with zero runtime tokens.
- [x] Boundary, Browsing, Buying, and Intent Override each retain Hit Rate@10 `1.0`.
- [x] Unit tests cover state isolation, override, exhaustion, output breadth, fallback, Gemini budgets/privacy/failures/cache, and evidence capture.
- [x] Default Agent execution is network-free and standard-library-only.
- [x] Optional Gemini calls are offline, quota-clamped, privacy-minimized, validated, cached, and failure-isolated.
- [x] Architecture, ablation, impact, feasibility, responsible-AI limitations, demo flow, and reproduction are documented.
- [x] Generated catalog, model cache, results, and evidence manifest are git-ignored.

## Team/External Actions — Must Be Completed Manually

- [ ] Confirm every team member is registered with the organizer and listed correctly on Devpost.
- [ ] Replace role-only contribution text with accurate individual names/roles in Devpost; do not invent attribution in the repository.
- [ ] Decide and publish the project license if the team/organizer requires one.
- [ ] Confirm the public repository is accessible and the submitted origin/commit are correct.
- [ ] Publish the exact catalog release asset URL and its checksum file; verify a clean-machine download/decompression flow.
- [ ] Record and publish the required public demo video; add its final URL to Devpost.
- [ ] Rehearse the full three-minute script and prepare the judge Q&A answers.
- [ ] Freeze the final commit and stop modifying Agent, prompts, indexes, model configuration, or solution assets after the deadline.
- [ ] From a clean tracked worktree at that commit, run `python tools/run_evidence.py` and retain `results.json` plus `evidence_manifest.json` outside git.
- [ ] Verify the retained manifest says `tracked_worktree_dirty: false` and contains the exact submitted commit hash.
- [ ] After the official hidden package is released, run only the unmodified evaluator against the frozen commit and retain all requested evidence.
- [ ] Report hidden results exactly as produced; do not claim them before that run.

## Final Freeze Commands

```powershell
python -m compileall starter evaluator tests tools
python -m unittest discover -s tests -v
python -m evaluator.local_evaluator
git status --short
git rev-parse HEAD
python tools/run_evidence.py
```

The evidence files are intentionally ignored. Copy them into the submission evidence package together with the commit hash, timestamp, hardware notes, and any organizer-requested logs.
