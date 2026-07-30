# Natural Synthetic Corpus v2

This frozen corpus supports anonymous route-coverage discovery on the RTX 4090
canary profile. It is deliberately synthetic and must not be treated as
internal real-traffic evidence or as permission to change a release profile.

`discovery.jsonl` contains 1,500 requests for shape discovery. `holdout.jsonl`
contains the disjoint 500-request confirmation set. Every record carries the
generation seed and hashes for the generator source, template data, and
generation configuration. `audit.json` is the canonical provenance and
distribution record.

The corpus uses complete Russian, English, and mixed-language statements in
stream, game-commentary, review, dialogue, event, and transition contexts. It
contains no random filler strategy, has 100 percent text uniqueness, and the
generator enforces the intended language and length-class quotas. The generated
`manual-review-100.jsonl` is a stable inspection sample; its current review
status is intentionally `pending_manual_review` until a human signs it off.

The intended workflow is discovery on the 1,500-request split, offline bucket
candidate calculation from its anonymous prefill-length histogram, then a
single correctness prototype. The holdout split is used only after that
prototype, with a changed order, speaker, and request seed.
