# Representative Benchmark Corpus v4

## Purpose

The v4 corpus measures end-to-end streaming behaviour under text that resembles
the intended application domain: an AI streamer speaking about games, chat,
technical incidents, donations, moderation, and transitions. It is not a
speech-quality training set and it does not prove general-language quality.

It was used for shape coverage, first-audio timing, route classification,
stability/soak manifests, and a frozen discovery holdout. It lets the project
distinguish a narrowly optimized exact shape from the eager behaviour that a
user is more likely to encounter.

## Composition

The completed v4 validation contains 2,000 unique records with these quotas:

| Dimension | Distribution |
| --- | --- |
| Language | Russian 1,300; English 500; mixed 200 |
| Length class | Micro 300; short 400; medium 700; long 400; extended 200 |
| Category | Conversation 320; game commentary 490; game dialogue 100; game review 260; live chat 380; stream event 330; transition 120 |

The original quota validation and repetition audit are committed with the
corpus in
[`representative-v4`](../benchmark-artifacts/rtx4090-2026-07-30/representative-v4/).
The final corpus candidates and targeted repairs are preserved as separate,
auditable stages instead of overwriting earlier evidence.

## Authorship and review

The corpus was LLM-assisted during authoring and repair. Prompts used
stream-language and scenario patterns drawn from real AI-stream contexts, then
ChatGPT was used to draft batches and alternatives. The corpus does **not**
contain verbatim stream transcripts and should not be described as one.

Automated validation covered JSONL shape, quotas, language labels, text
uniqueness, duplicate/repeated n-gram limits, replacement provenance, and
compatibility between source and overlays. AI pre-reviews were explicitly kept
as advisory evidence, not as a human gate. A human reviewer then accepted,
kept, or replaced the flagged records, including a targeted re-review of the
repairs and a 100-record general discovery review.

This process improves domain realism and protects the benchmark from obvious
template repetition, but it remains a project-specific workload. It should not
be treated as a population sample of all TTS requests.

## Holdout discipline

The 500-record frozen holdout is descriptive-only. Once frequency counts and
the exact allowlist were selected, the holdout was not used to add forms or
adjust scheduling. Its reports are split by compiled/eager route, exact length,
category, and language. New optimization work must use a fresh tuning set and
retain another untouched holdout for evaluation.
