# Deferred local speech work plan

Status: planning only, recorded 2026-11-12. This is a backlog and review scope,
not an accepted runtime ADR, implementation authorization or support claim.
Current R1 corrective work takes priority. See [the R2 roadmap](r2-roadmap.md).

## Sequence

1. Close the concurrent-stop and protected-path corrections and confirmed P1
   resource/publication defects. Verify integration and freeze a new exact R1
   candidate with runtime/model fingerprints.
2. Repeat mandatory supported-scope acceptance on CMP 50HX and RTX 4090. Add
   separately classified native Base and experimental RU-stress RTX trials;
   failed optional trials must not silently become mandatory support claims.
3. After R1, propose the composition ADR and test/API contract before coding.
   Keep standalone C++ CLI, latency research and composition PRs independent.

## Composition design to prepare for R2

Plan typed speech and pause operations, with an optional markup frontend.
Grammar examples such as `[voice:profile]`, `[pause:400ms]` and
`[style:whisper]` are illustrative, not a stable accepted syntax. Specify
escaping, scoping and validation; ordinary text must remain ordinary text.

The proposed ADR must cover:

- explicit backend capabilities, with errors for unsupported or unknown
  controls rather than silent fallback;
- deterministic silence in the canonical sample clock (400 ms at 24 kHz is
  9600 mono frames), shared by playback, WAV and animation timing;
- sequential ordering, one composition-level terminal result, cancellation
  and timeout propagation, bounded text/pause/buffer limits and backpressure;
- request-local voice/style state, with no leakage into unrelated requests;
- segment boundaries, click prevention, optional crossfade accounting,
  speaker-identity drift and the latency cost of splitting requests;
- tests for exact pause frames, cancellation during pauses and speech,
  unsupported styles, bounds, sequential reuse and WAV/playback timelines;
- human listening for continuity and identity on exact backend/model pairs.

Compare managed voice profiles, supported per-request CustomVoice instructions
and experimental steering separately. Switching profiles may change voice
identity; it is not proof of emotion control within one identity. Rate/volume
controls require explicit capability and accounting decisions. Nonverbal events
remain a later extension. Keep the current QTB and model inference boundaries.

## Local C-project investigation

Candidate: <https://github.com/gabriele-mastrapasqua/qwen3-tts>.
The external review reports inline markup, pauses, emotion recipes and extra
expressivity/steering assets. These reports have not been independently validated
by this documentation change. Do not describe them as integrated or supported.

For a future isolated study, pin the source revision and document:

- which features are code, extra assets, training or model-specific behavior;
- source and weight licenses, redistribution conditions and asset provenance;
- compatibility with the pinned qwentts.cpp model layout, quantization and ABI;
- what is reusable without training versus requiring new assets or an engine
  change, without assuming steering vectors are interchangeable;
- Russian quality, natural EOS, identity, sequential stability, cancellation,
  latency and memory against the unchanged local baseline.

The first deliverable is a feasibility report, not a new engine or dependency.
Qwen-Audio 3.x cloud integration is outside this plan and may never be pursued.

## RTX acceptance follow-up after the corrective freeze

Prepare a separate runbook/runner change only where necessary. Record exact
candidate, runtime/model/reference hashes, GPU UUID, driver/CUDA, corpus and
options; preserve earlier failed FP16 and partial BF16 evidence as historical.

- Native Base: pinned split Q8_0 talker/codec; cold, startup warmup, warmed and
  repeated requests, restart, EOS, cancellation/recovery, short/medium/long
  text, physical playback, WAV integrity and listening.
- RU-stress: exact converted model/profile and canonical 12-case corpus from
  [compatibility notes](russian-stress-model-compatibility.md) and
  [the CMP receipt](reports/russian-stress-cmp50hx-acceptance-2026-10-07.json).
  Verify effective text/U+0301 before inference. Missing assets are a missing
  gate, not permission to substitute official Base. Remain opt-in/experimental.
- Q4: optional, separately fingerprinted candidate; verify quality and EOS
  before interpreting speed. Do not assume it is faster than Q8_0.
- CustomVoice: explicit BF16 through installed CLI on RTX, repeated requests,
  EOS, WAV, playback and listening. Do not change global dtype defaults or
  transfer RTX settings to CMP.

Measure cold/load/warmup separately from first PCM and physical playback;
include repeated-request percentiles, chunk cadence, RTF and peak VRAM where
available. Historical CMP latency is comparison context, not RTX acceptance.
Keep native/RU-stress experimental if promotion gates fail. Small tracked
receipts and the release support matrix must reflect the actual scope; large
payloads stay in the protected ignored evidence tree with hashes and retention
information. No release publication precedes mandatory packaging, hardware and
listening gates.
