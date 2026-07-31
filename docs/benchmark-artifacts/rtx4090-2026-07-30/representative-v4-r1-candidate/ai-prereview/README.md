# AI Pre-Review Triage

These files are AI-generated review evidence. They are not human review and do
not satisfy either candidate gate.

- `targeted-review-98.ai-prereview.jsonl` is the 98-record review of existing
  repair replacements.
- `manual-review-form-100.ai-prereview.jsonl` is the 100-record general review.
- `ai-prereview-triage.json` is the original v1 triage artifact.
- `targeted-repair-authoring-52.jsonl` and
  `general-repair-authoring-12.jsonl` are the original v1 pending authoring
  forms.
- `ai-prereview-triage-v2.json` is the current SHA-pinned triage manifest. It
  records 52 targeted and 12 general findings, with `overlap_count = 0` and
  `unique_candidate_count = 64`.
- `targeted-human-adjudication-52.jsonl` and
  `general-human-adjudication-12.jsonl` are the current v2 human decision
  forms. They are intentionally pending and cannot be materialized.
- `ai-review-provenance.json` records the available import provenance. Model,
  prompt, and rubric details were not supplied with the imported AI reviews.

For each v2 row, a human reviewer must set `authoring_status` to
`completed_human_adjudication`, give a non-empty `author_id` and
`decision_notes`, and choose `replace` or `keep_after_human_review`.
`replace` requires a natural `proposed_replacement_text`; `keep_after_human_review`
requires that field to remain empty.

After all 64 rows are complete, create a separate revision with the canonical
acceptance command. It rebuilds the triage context from the pinned review
inputs, materializes the revised candidate, splits all ten batches, and runs
the full validation and repetition gates:

```powershell
.venv\Scripts\python.exe scripts\accept_corpus_v4_ai_prereview_revision.py `
  --base-candidate docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\candidate.jsonl `
  --triage-manifest docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\ai-prereview-triage-v2.json `
  --targeted-review-form docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\targeted-review-98.jsonl `
  --targeted-ai-prereview docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\targeted-review-98.ai-prereview.jsonl `
  --general-review-form docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\manual-review-form-100.jsonl `
  --general-ai-prereview docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\manual-review-form-100.ai-prereview.jsonl `
  --ai-review-provenance docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\ai-review-provenance.json `
  --targeted-adjudication docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\targeted-human-adjudication-52.jsonl `
  --general-adjudication docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r1-candidate\ai-prereview\general-human-adjudication-12.jsonl `
  --corpus-id representative-v4-r2-candidate `
  --output-dir docs\benchmark-artifacts\rtx4090-2026-07-30\representative-v4-r2-candidate
```

The output directory must be new. Accept the candidate only when its
`acceptance-report.json` has all four pass fields set to `true`:
`materialization_pass`, `corpus_validation_pass`, `repetition_pass`, and
`acceptance_pass`. The script creates the requested directory only after a
complete pass. A rejected run is preserved instead as a sibling directory named
`representative-v4-r2-candidate.rejected-...`; inspect its reports, correct the
forms, then reuse the original output path for the next attempt.

`ai-draft-proposals-64.json` and the two `*.ai-draft.jsonl` files are draft
wording proposed by Codex. They are deliberately marked
`ai_draft_pending_human_authoring`; they do not overwrite the blank forms and
must be reviewed, amended, or rejected by a human author before use.
