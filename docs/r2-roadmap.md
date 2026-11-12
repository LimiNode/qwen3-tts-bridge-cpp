# R2 roadmap (planning only)

Status: deferred until the R1 candidate is published. This document records
research and product direction; it does not authorize implementation, backend
replacement, model downloads, or a release claim.

## R2-A: standalone C++17 CLI

Implement a native peer to the installed Python `qwen-tts` command only after
R1 has a published, reproducible baseline. The C++ CLI must:

- reuse the existing C++17 SDK and execution components, without adding a
  second synthesis engine;
- implement the accepted language-independent command contract and compatible
  model/voice registry formats;
- preserve cancellation, output, error, and timeout semantics;
- be independently installable and packaged, with explicit backend/runtime
  dependencies;
- prove command-level parity with the Python CLI through shared integration
  cases and failure tests.

A native CLI does not imply Python-free inference for every backend. The Python
worker remains an explicit runtime option until a backend-specific acceptance
gate says otherwise.

## R2-B: `speech.cpp` low-latency research

Upstream reference: <https://github.com/nyosegawa/speech.cpp>, especially its
`docs/models/qwen3-tts.md`. The upstream RTX 2080 Vulkan figures sometimes
quoted for first PCM (approximately 24 ms p50 for 0.6B and 32 ms p50 for 1.7B)
are external reported measurements, not results for this bridge, CMP 50HX, or
RTX 4090.

Study, without promising adoption:

- codec state reuse and early chunk scheduling such as `1→1→2→4`;
- GPU graph preparation and execution for the code predictor;
- ggml/Vulkan behavior and Q8_0 quantization;
- measurement differences between first PCM, inter-chunk cadence, and first
  audible playback;
- memory cost, audio quality, EOS behavior, cancellation, and sequential
  stability alongside latency.

Each candidate optimization receives one classification:

- already implemented;
- potentially transferable;
- requires architectural changes;
- incompatible;
- unsupported by sufficient evidence.

Experiments must be isolated A/B runs on CMP 50HX and RTX 4090 with the same
comparable corpus/options where possible. A latency improvement is not
adoptable without quality, natural-EOS, cancellation, and stability gates.
Do not start a large-scale runtime replacement or speculative optimization in
R1.

## R2-C: local expressive speech composition

After R1, design a backend-neutral composition layer for explicit pauses,
voice-profile switching and per-segment style instructions. Keep spoken text
separate from control instructions; markup must compile to typed speech/pause
operations, not be passed literally to Qwen3-TTS. Reuse the existing C++17 SDK,
QTB, playback and WAV components rather than adding another synthesis engine.

The next documentation deliverables are a proposed ADR, backend capability
matrix, minimal public API and acceptance/test plan. Implementation is deferred
to R2. See [the deferred work plan](local-expressive-speech-plan.md) for the
required lifecycle, resource, audio and research gates.

The local C implementation
[gabriele-mastrapasqua/qwen3-tts](https://github.com/gabriele-mastrapasqua/qwen3-tts)
is a research candidate for expressive control and reported steering assets,
not an approved dependency or a planned engine replacement. Check a pinned
revision, code/asset licenses, model compatibility and Russian listening quality
before recommending reuse. Reported upstream features are not bridge evidence.

## Outside the committed roadmap: Qwen-Audio 3.x

The API-only Qwen-Audio 3.x service described in the external review is not a
planned backend, R1/R2 dependency or integration commitment. Cloud integration
has no schedule and may never be implemented: this project prioritizes local
inference. Keep it only as external context. Any future reconsideration requires
a separate product decision and fresh verification of weights, licenses and
deployment options; do not equate it with open-weight Qwen3-TTS or assume local
weights exist. Do not port its acoustic architecture into the current engine.

## Exit condition for R2

R2 work may begin only after R1 has an exact release tag, verified package
artifacts and checksums, a documented supported scope, and preserved evidence
for any unresolved optional profiles. The first R2 PR should remain either a
focused CLI contract/implementation change or an isolated research probe; do
not combine independent workstreams or rewrite historical acceptance receipts.
