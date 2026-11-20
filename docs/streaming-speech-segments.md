# Experimental complete-sentence streaming

`qwen_tts_play --segment-text --text "First sentence. Second sentence."`
enables an opt-in, model-neutral segment planner. The default single-request
route is unchanged. Native model inference still runs in the existing
persistent worker; no model reload or parallel GPU inference is introduced.

The planner's `qwen_tts_bridge/text/segmentation.hpp` entry point is independent
from the optional `tts-front-cpp` adapter. It returns exact half-open byte
ranges that partition the UTF-8 source. Combining accents, punctuation and
whitespace are retained, not regenerated or normalized by the planner.
Each segment is prepared once by the configured frontend before submission.
Offsets printed as `speech_segment source_begin/source_end` refer to the
original command text, not to potentially length-changing frontend output.

The conservative RU/EN heuristic recognizes sentence terminators and protects
decimal points, common abbreviations, initials, dotted acronyms, and balanced
quotes/brackets. Internal quoted sentences stay together. An unpunctuated final
utterance remains whole. This is not a full language parser: ambiguous
abbreviations can keep sentences together, and grammatical/prosodic continuity
still needs listening. It does not split at arbitrary words or commas and call
the result a completed sentence.

Default resource bounds are 1 MiB source, 4096 UTF-8 bytes per indivisible
segment, and 256 segments. All source boundaries and bounds are validated
before the worker starts. An oversized unpunctuated span fails explicitly;
the caller must provide a natural boundary. These are resource bounds, not
model token-count limits or calibrated EOS/duration thresholds.

Only one synthesis request is active at a time. After its terminal event the
next segment may generate while previous accepted audio is still playing.
All segments share a playback epoch, retaining already queued PCM; the
existing player's bounded queue provides backpressure. There is no unbounded
prefetch queue. The one-shot timeout is a single monotonic deadline across
preparation, all segment requests and final playback drain, not a fresh
timeout per segment. Any request/playback failure stops later submissions.
Each request retains the same explicit seed and voice settings; there is no
automatic reseeding, retry, EOS suppression or claim of full spoken coverage.

The existing terminal fade/padding applies to each segment. Raw PCM and WAV
capture concatenate ordered segment audio; WAV publication happens only after
all segment requests and playback complete. Earlier physically played audio
cannot be rolled back on a later failure. Per-request playback metrics and
animation receipts are rejected with this experimental option rather than
being mislabeled as valid multi-segment receipts.

The first composition is intentionally one-shot `--text` only. Interactive
replacement/cancellation, predictive lookahead, adaptive EOS recovery,
cross-segment prosody and actual hardware/listening qualification are not
claimed implemented by this planner. Mock tests verify exact text order,
complete capture, stop-on-failure and the shared deadline; real-model latency
and pronunciation remain separate acceptance gates.
