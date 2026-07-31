# Corpus V4 Batch Contract

Corpus v4 is assembled from ten independently reviewed JSONL batches of 200
original records. A batch is a quality-control unit, not independent evidence:
all batches may be generated with the same external language model.

Every record requires `text`, `language_class`, `category`, `scene_context`,
`speech_intent`, `intended_length_class`, `template_family_id`,
`semantic_intent_id`, `key_phrase_id`, `batch_id`, and `record_id`.

Batch IDs are `v4-b01` through `v4-b10`; record IDs must be exactly
`v4-bNN-001` through `v4-bNN-200`. Use
`scripts/prepare_corpus_v4_batch.py` to assign these immutable IDs to a
candidate JSONL file before validation. The preparer refuses to overwrite an
existing output or its SHA sidecar unless `--overwrite-output` is explicit.

The final 2,000 records must contain 1,300 `ru`, 500 `en`, and 200 `mixed`
records. Length quotas are 300 `micro`, 400 `short`, 700 `medium`, 400 `long`,
and 200 `extended` records. `validate_corpus_v4_batches.py` rejects a
cumulative quota overflow and, once ten batches are supplied, requires exact
completion of both quota tables. Final category quotas are 490
`game_commentary`, 380 `live_chat`, 320 `conversation`, 260 `game_review`, 100
`game_dialogue`, 330 `stream_event`, and 120 `transition` records.

Review one new batch at a time. Run its validator and repetition audit together
with every previously accepted batch before asking for the next batch. After
materialization passes the complete corpus contract, use
`scripts/split_corpus_v4_runtime.py` to create 1,500 discovery records, a
closed 500-record runtime-measurement holdout, and a deterministic
discovery-only stratified 100-record human-review sample.

## Repair Workflow

The quotas above remain frozen when a complete candidate fails the cumulative
repetition audit. Do not accept the observed category distribution as a new
contract and do not repair the difference by relabelling existing text.

Use `scripts/build_corpus_v4_repair_set.py` with the full audit JSON and the
combined, ID-assigned JSONL. Pass the immutable
`config/corpus-v4-repair-policy-v1.json` explicitly. The builder uses a
deterministic greedy multicover, bounded category-slot swap, reverse-delete
pass, and bounded local search;
its selected count is not claimed to be a global minimum. Its report exposes
each selection stage and the local-search trial count.

Run the audit with `--corpus-id representative-v4`. The audit, repair policy,
repair-set, and overlay are linked by SHA-256 values for the complete source
JSONL, its `record_id` set, the audit, and the policy. The repair-set stores
every immutable field that a replacement must preserve. Repetition-only entries
pin the exact category, scene context, and speech intent. Category-rebalance
entries pin the target category and require a newly authored metadata pair that
passes the corpus compatibility matrix.

Author one natural replacement per repair-set record in JSONL. Use
`scripts/build_corpus_v4_repair_overlay.py` to validate the reviewed authoring
rows and build the provenance-pinned overlay; it takes generated repair reasons
from the repair-set, so a form created before a later audit rebuild does not
need manual updates to those opaque identifiers. Authoring source, preserved
fields, word range, semantic target, and replacement metadata remain strict.
The builder rejects duplicate replacement metadata IDs across the authoring set.
It also rejects a replacement whose canonical text is unchanged, duplicates
another replacement, or collides with an unchanged source record. Canonical
text is Unicode NFKC normalization, whitespace collapse and trim, then
casefold.

Each overlay entry must preserve `batch_id`, `record_id`, `language_class`, and
`intended_length_class`; it must include a new `text`, new semantic metadata,
the target category/context/intent, and the source and replacement hashes. A
record changing category is a replacement with new text and metadata, never a
metadata-only reclassification.

Run `scripts/materialize_corpus_v4_overlay.py` to build the candidate JSONL.
Pass the same source JSONL, audit, repair policy, and repair-set used to build
the plan. It refuses incomplete overlays, altered source records, changed
immutable fields, semantic-target drift, target mismatches, incorrect hashes,
schema-version drift, a duplicate final canonical text, or a broken provenance
chain. Repair-set and overlay
entries use exact fail-closed schemas. The deterministic selector applies
greedy multicover, bounded category-slot swap search, reverse deletion, and
bounded local improvement; it reports local-search and slot-swap trial counts
but does not claim a global minimum. Then re-run the full ten-batch validator,
`scripts/audit_corpus_repetition.py --corpus-id representative-v4`, and human
review. Keep the source batches immutable; commit the repair-set, reviewed
overlay, materialization report, and resulting validation artifacts together
only after all gates pass.

Create the 98-row targeted replacement-review form with
`scripts/prepare_corpus_v4_targeted_review.py` and evaluate a completed form
with `scripts/evaluate_corpus_v4_targeted_review.py`. The gate checks the exact
authoring, repair-set, overlay, source/replacement text, and target metadata;
it passes only when one named human reviewer has completed every replacement
without a negative quality or metadata-only finding. A pending form, an AI
pre-review, or a blanket approval is not a completed human-review result.

## Candidate Quality Revisions

Keep an accepted corpus immutable. When a later AI pre-review identifies text
quality concerns, build a separate candidate rather than editing the frozen
source or relabelling records. Use
`scripts/prepare_corpus_v4_quality_overlay.py` with the frozen and corrected
general review forms, the explicit AI pre-review, and the existing repair set.
It produces a text-only overlay for records not already covered by the repair
set; the overlay pins the base corpus, every review input, source/replacement
hashes, and all preserved metadata. Then use
`scripts/materialize_corpus_v4_quality_overlay.py` to materialize the
candidate. The materializer independently rechecks provenance, preserved
metadata, word ranges, source/replacement hashes, and final canonical-text
uniqueness.

Re-run the complete ten-batch validation, full repetition audit, runtime split,
and create fresh targeted and general pending human-review forms for the
candidate. AI pre-review can identify repair candidates, but it never satisfies
either human-review gate or authorizes a runtime benchmark.

Use `scripts/prepare_corpus_v4_ai_prereview_triage.py` to retain an AI
pre-review as SHA-pinned evidence and to create separate pending human
adjudication forms for its flagged rows. It requires the exact 98-record
targeted and 100-record general forms, validates their schemas and scopes,
allows either scope to have zero findings, and rejects an overlap between the
two repair scopes.

Each human adjudication row must record one of two decisions:

```text
replace
keep_after_human_review
```

Both decisions require a non-empty `author_id` and `decision_notes`. A
`replace` decision also requires a non-empty `proposed_replacement_text`; a
`keep_after_human_review` decision requires that field to remain empty. AI
drafts are suggestions only and cannot make either decision. Every form row is
also pinned to the exact SHA-256 of the base candidate.

Use `scripts/accept_corpus_v4_ai_prereview_revision.py` only after every
flagged row has completed human adjudication. Its internal builder reconstructs
the exact v2 templates from the frozen 98/100 review forms, both SHA-pinned AI
pre-reviews, and AI-review provenance. It permits human changes only to the
decision, author identity, decision notes, and proposed replacement text; any
drift in AI notes, issues, source text, targets, or current candidate context
is rejected. It then materializes text-only replacements, preserves candidate
metadata, validates word ranges and canonical uniqueness, writes ten batches,
and runs the full validator and repetition audit. Treat the resulting candidate
as accepted only when `acceptance-report.json` records true for
`materialization_pass`, `corpus_validation_pass`, `repetition_pass`, and
`acceptance_pass`. Either zero-sized adjudication scope is valid only when the
SHA-pinned triage manifest itself expects zero rows.

The acceptance script verifies that the materialization report describes the
exact candidate that reaches the batch and repetition gates: supported builder
schema, candidate SHA-256, candidate `record_id` set SHA-256, base candidate,
triage, review, AI-provenance, and adjudication input hashes must all match.
Its acceptance report records this complete provenance chain together with the
builder, validator, and repetition-audit schema versions. It writes into a
sibling hidden pending directory and atomically publishes the requested output
directory only after all gates pass. A failure is retained under a unique
`<output>.rejected-...` directory with its available reports, so the requested
output name remains immediately reusable.
