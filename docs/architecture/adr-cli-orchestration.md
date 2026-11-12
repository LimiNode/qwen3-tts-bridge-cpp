# ADR: keep shared user contract over language-specific execution layers

- Status: accepted
- Date: 2026-11-11
- Baseline: `e0dc4b445923d2e37074eba2c636c4007e9bf6f2`

## Context

The project already exposes a Python `qwen-tts` command and functional C++
executables. The Python layer resolves configuration, models, voices, and
portable paths. The C++ layer owns the QTB client, PCM callbacks, WAV capture,
playback, and deterministic worker shutdown. The workers own model-specific
inference.

Reimplementing the complete `models` and `voices` surface in C++ without a
shared contract would duplicate Hugging Face cache rules, JSON configuration,
voice-registry transactions, and native preparation. It would also create two
incompatible user contracts for the same data.

## Decision

Keep one language-independent user command contract with two supported CLI
frontends. The current Python CLI is the reference implementation for this
functional wave; a standalone C++17 `qwen-tts-cpp.exe` is a planned peer
frontend after functional and manual acceptance. Both frontends must preserve
compatible persisted formats, normalized request semantics, and the shared
acceptance matrix:

```text
qwen-tts
    -> normalized command/request
    -> qwen_tts_save_wav.exe or qwen_tts_play.exe
    -> persistent Python or native worker

qwen-tts-cpp.exe (future)
    -> the same normalized command/request contract
    -> the same C++ execution components and compatible worker boundary
```

The Python CLI may select and validate a backend/profile, but it must delegate
framing, streaming, WAV encoding, playback, and transport lifecycle to the
existing C++ components. The C++ executables remain directly usable without
the Python CLI when the caller supplies a worker and resolved runtime options.

The current Python CLI owns the reference implementation of:

- command grammar and compatibility aliases;
- model discovery, explicit download, and profile resolution;
- managed voice registry and provenance publication;
- portable bundle/runtime path resolution;
- normalization of family, voice source, runtime, sink, and completion policy.

The future C++ CLI is not required to copy Python internals, but must implement
the same user-visible semantics and persisted formats. Its ownership split and
migration plan require a separate implementation ADR; this decision does not
authorize implementing it in the current CLI completion batch.

The C++ layer remains the canonical owner of:

- QTB framing and request callbacks;
- PCM delivery and playback;
- shared `WavWriter`/`WavCapture` behavior;
- process supervision and deterministic shutdown.

No second C++ model/voice registry and no second TTS engine are introduced by
the CLI completion work.

## Consequences

The architecture has one user contract and one implementation for each
execution concern, while allowing two equivalent frontend languages. Python
remains required for the Python backend and its portable runtime, while
native-worker invocations do not require Python for the model execution path.
C++ applications can bypass either user CLI entirely.

The boundary requires an explicit normalized request and disciplined output
publication. It also means that model-family additions must be checked in the
Python resolver and the selected worker backend before they are exposed as
user-facing aliases.

## Rejected alternative

Building the future C++ CLI before the current contract and acceptance matrix
are stable is deferred. A monolithic implementation that silently diverges
from Python is rejected. Reconsider it after functional/manual acceptance,
with a separate ADR covering ownership, compatibility, migration, and parity.

## Verification

The decision is verified by keeping direct C++ executable tests and Python CLI
tests in the same acceptance matrix. Mock-worker tests establish the boundary
without CUDA; real-model/GPU and listening checks remain separate acceptance
evidence.
