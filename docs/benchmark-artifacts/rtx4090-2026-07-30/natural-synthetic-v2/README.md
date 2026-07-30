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

## Discovery Result

The strict RTX 4090 profile completed the 1,500-request discovery run with one
persistent worker and `cancelled_after_audio` for every request. The exported
telemetry has complete terminal accounting and matching pinned provenance.

The current exact allowlist covers 125 of 1,500 requests (8.33 percent). The
unknown-length distribution is broad rather than concentrated: only 37.96
percent of unknown requests meet the configured 30-samples-per-length rule.
The route-coverage gate therefore returns `collect_more_anonymous_coverage`.
No padded-bucket prototype, runtime-profile update, or scheduler change is
authorized by this artifact.

`discovery-1500-padded-bucket-candidates.json` is an offline, research-only
calculation. It records 4/5/6-bucket possibilities and their padding/fallback
trade-offs so a later, separately approved experiment has an auditable input.
