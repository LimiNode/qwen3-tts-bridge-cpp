# Representative V4 R1 Candidate

This is a candidate quality revision of the frozen `representative-v4` corpus.
It is not accepted for runtime discovery or benchmarking.

## Construction

The candidate first materializes the corrected 98-record repair overlay from
the frozen corpus. It then applies `quality-overlay-31.jsonl`, a separate
text-only overlay prepared from the corrected general review form. All
non-text metadata is preserved by the second overlay. The source corpus and
the full candidate both contain 2,000 records.

`v4-b06-168` has one additional targeted wording correction to remove a
corpus-wide repeated four-gram. `v4-b03-028` has one additional quality-overlay
correction to remove an exact collision with `v4-b06-028`.

The source AI pre-review files and their change manifest live beside the frozen
corpus in `../representative-v4`. They are provenance evidence only and remain
explicitly `ai_prereview_not_human_gate`.

## Verified Artifact Gates

- `candidate-full-batch-validation.json`: ten valid 200-record batches and
  exact corpus quotas.
- `candidate-repetition-audit.json`: full 2,000-record repetition audit passes.
- `runtime-split-audit.json`: deterministic 1,500-record discovery and closed
  500-record holdout, with all ten batches represented.
- `targeted-review-98.json`: fresh pending human review of every replacement.
- `manual-review-form-100.jsonl`: fresh pending general human review sampled
  only from the candidate discovery split.

## Required Human Gates

Do not alter the two review forms' source or provenance fields. One named human
reviewer must complete every record in both forms. Then run:

```powershell
.venv\Scripts\python.exe scripts\evaluate_corpus_v4_targeted_review.py `
  docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\targeted-review-98.jsonl `
  --authoring docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4\reviewed-authoring-98-corrected.jsonl `
  --repair-set docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4\repair-set.json `
  --overlay docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\corrected-repair-overlay-98.json `
  --output docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\targeted-review-98-summary.json

.venv\Scripts\python.exe scripts\evaluate_corpus_manual_review.py `
  docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\manual-review-form-100.jsonl `
  --frozen-sample docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\manual-review-100.jsonl `
  --audit docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\runtime-split-audit.json `
  --output docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\manual-review-100-summary.json
```

The pending forms are expected to fail closed before this review is complete.
No RTX discovery run was performed for this candidate.
