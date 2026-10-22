# Project status and verified architecture

This document is the short, evidence-backed status summary for
`qwen3-tts-bridge-cpp`. It records what has actually been built and exercised,
while keeping experimental paths separate from the production baseline.

## Production baseline

The accepted release and packaging route is the persistent Python worker:

```text
QwenTtsClient -> QTB stdin/stdout -> persistent Python/PyTorch worker -> PCM
```

It keeps the model loaded between requests, exposes the async C++ API, streams
PCM, and supports request IDs, cancellation, terminal lifecycle events, and
portable/Nuitka packaging with models stored outside Git. This is the route to
use when a product needs the currently supported bridge behavior.

## Verified milestones

### Native qwentts.cpp runtime and DLL

The repository contains a working opt-in native path based on the pinned
`LimiNode/qwentts.cpp` fork. The native build enables `QWEN_SHARED=ON`, produces
the shared `qwen.dll`, and the bridge ABI adapter and native worker can load the
split talker/codec runtime and stream PCM on the validated CMP 50HX setup.
The canonical acceptance receipt records qwentts revision `130cb99`, ABI 6,
CUDA graphs enabled, and the exact worker/talker/codec hashes used for the run.

This is a real build and runtime milestone, not a claim that native is the
default backend. The native worker and the in-process DLL adapter remain opt-in
until the documented quality, cancellation, lifecycle, packaging, and
target-hardware promotion gates are closed. See
[`native-qwentts-backend.md`](native-qwentts-backend.md),
[`native-qwentts-worker.md`](native-qwentts-worker.md), and the boundary ADR
[`architecture/adr-native-engine-boundaries.md`](architecture/adr-native-engine-boundaries.md).

### Russian stress model and explicit accents

The experimental `ru-stress` talker/codec pair was converted for the native
split runtime and exercised with the registered
`kraftwerk_robot_ru_warm` voice profile. The model follows the source model's
explicit combining-accent contract: U+0301 is rendered only when the selected
profile advertises `explicit_combining_stress`.

The canonical CMP 50HX acceptance receipt records:

* 12 Russian utterances, including homographs, numbers, abbreviations, plain
  text, and a long operational sentence;
* non-empty PCM, natural EOS, and no starvation in all 12 cases;
* a human-listening pass: intelligible Russian, intended explicit stresses, and
  preserved warm Kraftwerk voice identity;
* fixed provenance for qwentts revision/ABI, GPU, voice, seed, and talker and
  codec hashes.

Primary evidence:

* [`russian-stress-cmp50hx-acceptance-2026-10-07.json`](reports/russian-stress-cmp50hx-acceptance-2026-10-07.json)
* [`russian-stress-kraftwerk-profile-ab.json`](reports/russian-stress-kraftwerk-profile-ab.json)
* [`russian-stress-model-compatibility.md`](russian-stress-model-compatibility.md)
* [`russian-stress-oracle-parity.json`](reports/russian-stress-oracle-parity.json)

The result is **experimental and opt-in**. The production default was not
changed, and the upstream stress repository is not treated as directly
compatible with the native split loader without the documented conversion.

### Text preparation and playback/animation plumbing

`tts-front-cpp` v0.2.2 is integrated as a model-neutral preparation boundary:

```text
raw text -> TextFrontend -> PreparedText -> QwenTtsClient
```

`PreparedText` carries normalized text, pronunciation evidence, semantic stress
decisions, warnings, and uncertainty. The Qwen adapter renders U+0301 only for
an explicitly compatible stress capability; the bridge does not guess from a
profile name.
The bridge pins the frontend at commit
`f828893b46728544041ab577215640338756a9d4` (tag `v0.2.2`).

The bridge also has a verified optional speech-animation adapter. It forwards
playback PCM first, maps the canonical sample clock to animation-neutral timing,
and isolates animation queue/analyzer failures from TTS lifecycle. The archived
real-Qwen CMP 50HX receipt demonstrates contiguous PCM and animation ranges,
terminal fade anchored at the real PCM end, zero queue overflow, and a measurable
`mouth_open` signal. This proves the audio-reactive v0 data path, not complete
avatar or lip-sync presentation.

See [`tts-front-integration.md`](tts-front-integration.md),
[`speech-animation-integration.md`](speech-animation-integration.md), and the
[real-Qwen speech-animation receipt](reports/speech-animation-qwen-e2e-cmp50hx-20261009/README.md).

## Current architecture

```text
Application
    |
    +--> optional tts-front-cpp v0.2.2
    |        |
    |        v
    |     PreparedText / pronunciation evidence
    |        |
    `------> QwenTtsClient
                 |
                 v
              QTB stdin/stdout
                 |
                 v
            selected worker
              |             |
              |             `--> optional native -> qwen.dll -> qwentts.cpp / GGML / CUDA
              `-----------------> persistent Python -> PyTorch / Qwen runtime
                               |
                               v
                         PCM + canonical sample clock
                               |
                               +--> application-owned sink / optional WinMM playback
                               |
                               `--> optional speech-animation adapter
                                        sample-addressed animation timeline
                                        physical playback-cursor acceptance pending
```

The dependency direction is deliberate:

* `tts-front-cpp` provides model-neutral preparation; it does not contain Qwen
  runtime logic.
* The bridge owns worker supervision, protocol, request lifecycle, PCM, and
  sample-addressed timing.
* Python and native engines are interchangeable backend routes behind the same
  client boundary.
* Playback and animation are downstream consumers. Animation must not delay,
  rewrite, or turn a successful PCM request into a TTS error.
* `speech-animation` remains generic and optional; avatar presentation adapters
  (VRM, Unity, Godot, and similar) are not claimed complete. The receipt proves
  a sample-addressed animation timeline, not physical playback-cursor
  synchronization.
* `tts-front-cpp` is optional; callers may provide already prepared requests or
  use another pronunciation provider.

## Status boundaries and next gates

| Area | Status | Boundary |
| --- | --- | --- |
| Persistent Python worker | Accepted production/packaging route | Continue release validation on the selected model and hardware |
| Native worker and `qwen.dll` | Working, opt-in experimental | Close promotion gates before changing the default |
| RU-stress + Kraftwerk profile | Hardware/listening validated, opt-in experimental | Expand long-run, cancellation, and packaging evidence |
| `tts-front-cpp` v0.2.2 | Integrated preparation contract | Keep frontend model-neutral |
| PCM/sample-addressed animation | Audio-reactive v0 baseline validated | Predictive visemes and presentation remain downstream work |
| Avatar presentation | Not yet complete | Add a separate VRM/Unity/Godot adapter after playback-locked cues are stable |

Model weights, DLLs, CUDA runtimes, generated builds, and WAV captures remain
external artifacts. The committed receipts contain provenance and measurements,
not the model data itself.
