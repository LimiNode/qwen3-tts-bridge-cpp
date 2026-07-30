# AI Pre-Review Triage

These files are AI-generated review evidence. They are not human review and do
not satisfy either candidate gate.

- `targeted-review-98.ai-prereview.jsonl` is the 98-record review of existing
  repair replacements.
- `manual-review-form-100.ai-prereview.jsonl` is the 100-record general review.
- `ai-prereview-triage.json` pins both inputs by SHA-256 and records only the
  rows that the AI flagged.
- `targeted-repair-authoring-52.jsonl` and
  `general-repair-authoring-12.jsonl` are pending human authoring forms.

The authoring forms are intentionally not accepted by either overlay
materializer. Preserve their identity fields, write a natural replacement into
`proposed_replacement_text`, give the author a non-empty `author_id`, and use a
new provenance-pinned repair workflow to validate any completed proposals.

`ai-draft-proposals-64.json` and the two `*.ai-draft.jsonl` files are draft
wording proposed by Codex. They are deliberately marked
`ai_draft_pending_human_authoring`; they do not overwrite the blank forms and
must be reviewed, amended, or rejected by a human author before use.
