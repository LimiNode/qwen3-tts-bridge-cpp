# ADR: keep Python user orchestration over shared C++ execution

- Status: accepted
- Date: 2026-11-11
- Baseline: `e0dc4b445923d2e37074eba2c636c4007e9bf6f2`

## Context

The project already exposes a Python `qwen-tts` command and functional C++
executables. The Python layer resolves configuration, models, voices, and
portable paths. The C++ layer owns the QTB client, PCM callbacks, WAV capture,
playback, and deterministic worker shutdown. The workers own model-specific
inference.

Reimplementing the complete `models` and `voices` surface in C++ would duplicate
Hugging Face cache rules, JSON configuration, voice-registry transactions, and
native preparation. It would also create two user contracts for the same data.

## Decision

Keep Python as the single user-facing orchestration layer and keep C++ as the
shared execution layer:

```text
qwen-tts
    -> normalized command/request
    -> qwen_tts_save_wav.exe or qwen_tts_play.exe
    -> persistent Python or native worker
```

The Python CLI may select and validate a backend/profile, but it must delegate
framing, streaming, WAV encoding, playback, and transport lifecycle to the
existing C++ components. The C++ executables remain directly usable without
the Python CLI when the caller supplies a worker and resolved runtime options.

`qwen-tts` is therefore the canonical owner of:

- command grammar and compatibility aliases;
- model discovery, explicit download, and profile resolution;
- managed voice registry and provenance publication;
- portable bundle/runtime path resolution;
- normalization of family, voice source, runtime, sink, and completion policy.

The C++ layer remains the canonical owner of:

- QTB framing and request callbacks;
- PCM delivery and playback;
- shared `WavWriter`/`WavCapture` behavior;
- process supervision and deterministic shutdown.

No second C++ model/voice registry and no second TTS engine are introduced by
the CLI completion work.

## Consequences

The architecture has one user contract and one implementation for each
execution concern. Python remains required for the Python backend and its
portable runtime, while native-worker invocations do not require Python for
the model execution path. C++ applications can bypass the user CLI entirely.

The boundary requires an explicit normalized request and disciplined output
publication. It also means that model-family additions must be checked in the
Python resolver and the selected worker backend before they are exposed as
user-facing aliases.

## Rejected alternative

Building a monolithic `qwen-tts.exe` in C++ is deferred. It would move cache,
configuration, registry, and portable-runtime policy into a second language
implementation before the current contract is stable. Reconsider it only after
the Python contract is complete, duplication is measured, and a separate ADR
defines migration and compatibility requirements.

## Verification

The decision is verified by keeping direct C++ executable tests and Python CLI
tests in the same acceptance matrix. Mock-worker tests establish the boundary
without CUDA; real-model/GPU and listening checks remain separate acceptance
evidence.
