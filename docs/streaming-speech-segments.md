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

## Local verification, 2026-11-20

MSVC x64 Release with frontend, WinMM, native worker and test hooks enabled:
**48/48 CTest PASS**. The compiled C++ source matches `6194dc50`; the final
Python probe formatting does not change its behavior. Python 3.11's full suite
passes **517 tests, 7 skipped**; Ruff and Pyright pass. The initial replay
analyzer's eight model-free tests are included in that suite. A subsequent
causality regression adds a ninth analyzer test; it separates text-only gate
eligibility from future terminal labels without changing the discovery
measurements. The independent
g++ segmentation unit probe and public-header build also pass.

The first full run is preserved, not counted as green. Its native-worker
failure exposed a pre-existing test race: stdout completion precedes stderr
telemetry, and the test read the diagnostic string concurrently with its
callback writer. Commit `aec48ac3` moves the existing stop/join before that
read; no worker ordering or timeout was changed. The corrected native test
passed 3/3 repetitions and the final full suite. A separate client startup
failed once; its unchanged test passed 3/3 repetitions and the final suite.
That isolated startup failure was not root-caused or claimed fixed.

Logs are repository-root-relative under `.tmp/streaming-eos-research/`:

| Log | SHA-256 |
| --- | --- |
| `full-ctest.log` (historical failed run) | `7b3d3601e60ea3b459313f4bd6d887ea09625e2f6d61cf47a3df87d01f8c8da3` |
| `full-ctest-after-stderr-join.log` | `b14e8e9aa56077c1ee98d742ce1e5f41e529dc4fc415a20e7e025b75280db02f` |
| `native-repeat.log` | `8d91680541f8bcacdc297aab92b27194d983aa6989f24f19493862e91a17ed59` |
| `client-repeat.log` | `b45b5a52946589acff2c4872d289c871192b7e6d1cdeb92984542037aa59f1b0` |

These are model-free regression results, not hardware/listening qualification.
See the [EOS/source research and next experiments](streaming-eos-next-experiments.md)
for the separate recovery, performance and dual-GPU work still required.
