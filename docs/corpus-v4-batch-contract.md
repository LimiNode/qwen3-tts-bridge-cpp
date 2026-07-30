# Corpus V4 Batch Contract

Corpus v4 is assembled from ten independently reviewed JSONL batches of 200
original records. A batch is a quality-control unit, not independent evidence:
all batches may be generated with the same external language model.

Every record requires `text`, `language_class`, `category`, `scene_context`,
`speech_intent`, `intended_length_class`, `template_family_id`,
`semantic_intent_id`, and `key_phrase_id`.

The final 2,000 records must contain 1,300 `ru`, 500 `en`, and 200 `mixed`
records. Length quotas are 300 `micro`, 400 `short`, 700 `medium`, 400 `long`,
and 200 `extended` records. `validate_corpus_v4_batches.py` rejects a
cumulative quota overflow and, once ten batches are supplied, requires exact
completion of both quota tables.

Review one new batch at a time. Run its validator and repetition audit together
with every previously accepted batch before asking for the next batch. After ten
batches pass, split each batch deterministically into 150 discovery records and
50 blind-holdout records. The formal 100-record human review must draw ten
records from each discovery partition only.
