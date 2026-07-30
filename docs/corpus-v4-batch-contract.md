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
with every previously accepted batch before asking for the next batch. After ten
batches pass, split each batch deterministically into 150 discovery records and
50 blind-holdout records. The formal 100-record human review must draw ten
records from each discovery partition only.
