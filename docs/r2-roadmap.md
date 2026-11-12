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

## Exit condition for R2

R2 work may begin only after R1 has an exact release tag, verified package
artifacts and checksums, a documented supported scope, and preserved evidence
for any unresolved optional profiles. The first R2 PR should remain either a
focused CLI contract/implementation change or an isolated research probe; do
not combine both workstreams or rewrite historical acceptance receipts.
