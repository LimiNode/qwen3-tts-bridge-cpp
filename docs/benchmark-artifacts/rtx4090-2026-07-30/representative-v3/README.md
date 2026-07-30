# Representative Streamer/Game Corpus v3

This frozen synthetic corpus is the candidate input for future RTX 4090 route
and shape discovery. It replaces v2 for that purpose; v2 remains useful only
as a telemetry-pipeline corpus.

The corpus has 1,500 disjoint discovery records and a frozen 500-record
holdout. Its intended length distribution is micro 15 percent (1--3 words),
short 20 percent (4--7), medium 35 percent (8--18), long 20 percent (19--35),
and extended 10 percent (36--65). Category-specific vocabulary covers live
chat, gameplay commentary, reviews, dialogue, stream events, and transitions.
Mixed-language records limit code switching to common game and streaming terms
such as Steam, Discord, FPS, boss, cooldown, patch, build, lobby, ranked, and
RTX.

Each record has `template_family_id`, `semantic_intent_id`, and
`key_phrase_id`. The automated preflight in `audit.json` checks all length and
language contracts, text uniqueness, a maximum family share of two percent, a
maximum intent share of five percent, and at most ten occurrences per recorded
key phrase.

`manual-review-form-100.jsonl` must be completed by a human reviewer before
any GPU discovery. Its evaluator requires category fidelity, naturalness,
likely real use, grammar, appropriate length, semantic repetition, and
mixed-language code-switch assessments. Automated preflight passing is not a
human-audit pass and does not authorize a runtime prototype.
