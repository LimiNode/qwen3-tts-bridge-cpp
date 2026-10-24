# Windows beta release scope

Status: proposed B2-0 scope contract. This document is deliberately
documentation-only. It does not announce a release, select a tag, change the
runtime, or replace the acceptance reports in `docs/`.

The scope is based on `main` at
`232e57f09bf4ab91dae9cf96bf14d907420ca8b5` and the Phase B1 inventory in
[`beta-capability-matrix.md`](beta-capability-matrix.md). “Verified” below
means that implementation and evidence exist; “supported” is the narrower
product promise for the first beta.

## Recommended first-beta contract

### Required production baseline

The first beta should advertise one conservative, reproducible path:

* Windows x64;
* the persistent Python worker using the pinned FasterQwen/Qwen streaming
  runtime;
* Qwen3-TTS **Base 1.7B** with a registered `voice_id` profile;
* UTF-8 text, language, instruction/voice profile, streaming `s16le` mono PCM,
  WAV output, cancellation, restart and deterministic terminal lifecycle;
* the documented CMP 50HX acceptance profile, with exact model/runtime/voice
  manifests supplied outside the repository.

Base 1.7B is the recommended required family because it has the strongest
current persistent-worker, playback, EOS, cancellation/recovery and human
listening evidence. This is a scope recommendation, not a claim that other
families are incompatible.

### Experimental availability

The following may remain available behind explicit opt-in switches or profiles,
but must not be described as the default production backend:

* native `qwentts.cpp` process worker and the optional in-process native path;
* the RU-stress profile with profile-owned model identity and combining U+0301;
* the build-tree speech-animation adapter;

The RU-stress profile already has a successful CMP listening/PCM receipt, but
its deployment status remains experimental. Native has strong ABI-6/CMP
evidence but still has a separate promotion and packaging gate.

WinMM is a separately classified optional playback module. Its installed target
and lifecycle/receipt tests are already verified, while device-specific use
still requires the documented playback acceptance gate.

### Deferred or conditional model families

* **CustomVoice 0.6B:** recommended as the next conditional beta row. Include
  only after the existing persistent-worker/player matrix, exact external
  model manifest, and Ryan/Serena listening gate pass.
* **CustomVoice 1.7B:** defer until a size-specific real acceptance exists.
* **Base 0.6B:** defer unless a product scenario requires that size and a
  variant-specific acceptance is recorded.
* **VoiceDesign 1.7B:** keep API and mock wrapper available, but defer the
  advertised beta claim until real model load, instruction behavior, PCM/EOS,
  and human quality are accepted.

This avoids promoting an entire model family from one Base 1.7B result. The
scope can be widened later without changing the core protocol.

## Release-facing CLI contract

The required user-facing commands are intentionally small:

| Command | Required first-beta use | Minimum contract |
|---|---|---|
| `qwen_tts_save_wav` | scriptable WAV generation and automation | worker/runtime selection, model path, text, language, registered `voice_id` (or selected speaker where the accepted model requires it), output path, timeout, and an explicit `--require-natural-eos` acceptance check when natural EOS is required |
| `qwen_tts_play` | interactive playback and cancellation | worker/runtime selection, model/profile selection, text, language, cancellation, tail enabled by default with `--no-tail` opt-out, and playback diagnostics |

`qwen_tts_latency_benchmark` and the speech-animation probe remain diagnostic
tools, not release UX requirements. The first beta does not require unifying
all example option parsers. Direct reference-audio, seed and sampling options
in `qwen_tts_save_wav` are an explicit follow-up decision; registered Base
profiles are the supported clone interface for this scope. A successful
`qwen_tts_save_wav` invocation does not by itself enforce natural EOS unless
`--require-natural-eos` is supplied; natural EOS remains mandatory in the
release acceptance receipt for every supported model run. Bit-identical audio
is not promised without a fixed-seed, fixed-runtime evidence record.

## Audio and DSP scope

Required:

* raw streamed PCM with the documented sample format and sample clock;
* WAV writing;
* optional physical playback as a separate sink;
* terminal fade and completion/cancellation padding through the existing
  postprocessor chain. `qwen_tts_play` enables the tail by default and accepts
  `--no-tail`; `qwen_tts_save_wav` leaves it disabled by default and accepts
  `--tail` to enable it;
* playback receipts and diagnostics that do not rewrite synthesis lifecycle.

Not required for the first beta:

* EQ, compressor, limiter, denoise, reverb, pitch or speed effects;
* Telephone/Radio or other named presets;
* a general effects graph or realtime DSP framework;
* predictive visemes, avatar presentation, or display-latency claims.

The proposed first beta excludes named presets. Revisit them only through a
later scope decision with a concrete product use case, expected output,
latency, and quality acceptance; no effects framework is implied here.

## Backend and provisioning policy

The Python persistent worker is the release baseline. Native is opt-in and
requires its own ABI/runtime manifest, DLL hash, model hashes and acceptance
receipt. No backend switch may silently change the advertised support level.

Models and reference audio are external artifacts. The beta provisioning
contract is:

1. obtain the exact model revision from the documented provenance;
2. place it at an explicit configured path or profile root;
3. verify the runtime/model manifest and SHA-256 files with the existing doctor
   or native manifest loader;
4. run offline after provisioning without an implicit download;
5. record model family, revision, voice registry/reference hash, device,
   runtime, seed and request corpus in the acceptance receipt.

Automatic Python downloading is not required for this beta. Native URL/SHA-256
bootstrap remains an opt-in capability, not a promise that all model families
are downloadable by the application.

## Promotion criteria for optional capabilities

| Capability | Promotion gate |
|---|---|
| CustomVoice 0.6B | Exact sealed package, persistent-worker sequential requests, non-empty PCM, natural EOS, physical playback, and Ryan/Serena human listening on the selected hardware/runtime |
| CustomVoice 1.7B or Base 0.6B | The same matrix with a variant-specific model manifest and receipt; no size-generalization from another row |
| VoiceDesign 1.7B | Real model/instruction load, non-empty PCM/EOS, restart/cancellation, WAV/playback, and human intelligibility/voice-design quality gate |
| Native worker | ABI/export/runtime-manifest verification, package/load gate, lifecycle/cancellation/recovery parity with Python, selected model listening, and explicit opt-in documentation |
| RU-stress | Preserve profile-owned identity and provenance, repeat the stress corpus after any frontend/model change, and keep experimental/default-off status until a product support decision |
| WinMM | Installed optional target, device/playback failure isolation, cursor/receipt evidence, and a documented single-sink integration contract; optional supported module, not a default backend |
| Speech-animation | Existing real-Qwen contiguous PCM/cue receipt remains required; predictive visemes and avatar presentation need a separate acceptance contract |

## Release blockers and measurable gates

The following are P1 blockers for a long-lived beta worker and must be resolved
before unattended service claims:

1. **Terminal history policy and bounded storage.** Enforce the selected
   strict acceptance-order request-ID policy, with idempotent late cancel and
   deterministic shutdown cancellation. Then verify bounded Python and native
   state with large sequential request counts, duplicate active IDs, maximum-ID
   exhaustion and the chosen late-cancel behavior.
2. **Pending admission.** Define a cap covering queued and running requests,
   reject excess work with `resource_error/resource_exhausted`, report the
   effective limit, and test cancellation followed by replacement admission in
   both workers. The cap value is a B2 implementation decision, not a hidden
   scope assumption here.
3. **Selected-model packaging acceptance.** On CMP 50HX, perform the isolated
   clean-environment portable package/doctor/C++ playback/listening gate for
   every required model row. Freeze binaries, manifests, hashes and request
   corpus before independent RTX 4090 validation.

The tts-front update to v0.2.3 is a B2 dependency task. Its acceptance gate is
effective UTF-8 comparison on a fixed corpus, adapter regressions, and targeted
listening only for changed or affected stress/number/currency/agreement cases.

## Compatibility and non-goals

The beta promises Windows x64, UTF-8 request text, the versioned QTB protocol,
async request IDs, streaming PCM, cancellation, WAV output and the selected
Python Base 1.7B profile. It does not promise:

* every Qwen model family or size;
* native backend parity by default;
* automatic model download or bundled model weights;
* a complete audio-effects suite;
* cross-platform support beyond the documented Windows target;
* predictive phoneme/viseme alignment, Unity/Godot/VRM presentation, or
  display-latency guarantees;
* numerical or latency equivalence between CMP 50HX and RTX 4090 when engine,
  model, runtime, driver or playback policy differs.

These are deferred capabilities, not accidental omissions. Widening the scope
requires a new acceptance row and a new evidence receipt rather than changing
the meaning of the Base 1.7B baseline.
