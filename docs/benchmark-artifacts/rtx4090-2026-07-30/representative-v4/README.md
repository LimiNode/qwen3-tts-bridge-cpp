# Representative Corpus V4

This directory freezes the provenance package for the 2,000-record
`representative-v4` corpus used by future RTX 4090 route and shape discovery.

The corpus was assembled from ten immutable ID-assigned source batches, then
repaired through a SHA-pinned source audit, repair policy, repair set, reviewed
authoring form, overlay, and materialization report. The materialized corpus
passes the complete ten-batch contract and the repetition audit.

All 98 replacements have a project-owner targeted review attestation in
`targeted-review-98.jsonl`. This attestation is intentionally labelled as such;
it is not a synthetic or automatic human-review result.

`discovery.jsonl` contains 1,500 records. The 500 records in
`runtime-measurement-holdout.jsonl` are closed to discovery and optimizer work.
`manual-review-100.jsonl` is a deterministic, discovery-only stratified sample,
and `manual-review-form-100.jsonl` must be completed by one human reviewer and
passed through `scripts/evaluate_corpus_manual_review.py` before any RTX
discovery run is authorized.

`SHA256SUMS.json` identifies every artifact in this directory. The manifest is
the portable inventory; the JSON reports contain the linked provenance hashes
for the repair and split pipelines.
