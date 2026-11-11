# User CLI command contract

- Status: active architecture contract
- Baseline: `e0dc4b445923d2e37074eba2c636c4007e9bf6f2`
- Scope: the installed `qwen-tts` command and the C++ executables it composes

## Boundary and ownership

The repository has two CLI levels. They are complementary, not competing
implementations:

```text
qwen-tts (Python)
    user-facing command grammar, configuration, model/voice resolution,
    output publication, and portable-runtime discovery

qwen_tts_save_wav.exe / qwen_tts_play.exe (C++)
    QTB client execution, PCM delivery, WAV capture, playback, and shutdown

qwen_tts_worker / qwen_tts_native_worker.exe
    model-specific backend execution behind the existing worker boundary
```

The Python CLI must not reimplement framing, synthesis callbacks, WAV encoding,
or playback. The C++ examples must remain directly runnable for applications
that already have a resolved worker and model configuration; they are not a
second user-facing model and voice registry.

The native and Python workers remain independent backend implementations. A
user command selects a backend/profile through normalized configuration; it
does not change the QTB protocol or create a parallel engine.

## Command matrix

| Command | User-visible result | Required inputs | Output ownership |
| --- | --- | --- | --- |
| `models list` | Discover local model candidates, including invalid ones | optional config/root | Python resolver; no implicit download |
| `models verify` | Verify one resolved model/profile | explicit model or native profile | Python resolver/receipt |
| `models download` | Explicitly acquire a model | explicit model/profile | Python downloader/cache |
| `synth` | Produce an audio artifact | text, model family/voice source, `--out` | C++ WAV writer, then guarded Python publication |
| `play` | Stream synthesis to the playback sink | text, model family/voice source | C++ playback; optional simultaneous WAV capture |
| `voices add` | Register an external reference WAV | voice ID and reference metadata | Python voice registry |
| `voices create` | Generate and register a VoiceDesign reference | voice ID, instruction, sample text | C++ synthesis + Python registry publication |
| `voices list/show/verify/prepare` | Inspect or prepare managed voices | command-specific voice ID | Python voice registry/native preparation |
| `design` | Legacy VoiceDesign preview | text, instruction, `--out` | Compatibility wrapper over VoiceDesign synthesis |

`voices create` is intentionally different from Base voice cloning: it first
generates a managed reference artifact with VoiceDesign and only then publishes
the registry entry. It must not claim to create a model checkpoint.

## Canonical generation fields

Every generation command is normalized before launching a worker. The internal
request shape keeps these concerns separate:

```text
model_family
model/checkpoint identity
voice source (voice_id, speaker, reference input, or instruction)
text and language
runtime backend/device/dtype
sampling parameters
output sinks and completion policy
timeouts and diagnostics
```

The public command grammar may expose only the fields valid for the selected
family. Invalid combinations fail before worker startup and before filesystem
publication. A family selection never silently falls back to another model,
backend, or device.

The supported family names are a user-facing contract only after their concrete
model identities and backend compatibility are verified:

```text
base-1.7b   base-0.6b   custom-1.7b   custom-0.6b   voice-design
```

The existing `--model` option remains an explicit path to a concrete model. It
is not replaced by a family alias.

## Output and failure rules

`--out` has command-specific meaning:

- `synth` requires `--out`; success requires a valid WAV and completion
  evidence, followed by guarded publication.
- `play` does not require `--out`; without it, playback is the only requested
  sink. With it, playback and one simultaneous WAV capture are requested.
- `design` keeps its legacy required output and optional `--play` compatibility
  behavior.

Output files are first written to owned temporary paths and published only
after completion, validation, and the requested sink policy succeed. A failed
capture or playback sink must not publish a misleading successful artifact.
An output failure is reported in the command exit status and diagnostics; it
must not corrupt an unrelated playback callback or registry entry.

No command implicitly downloads a model or mutates the voice registry. Those
operations remain explicit (`models download`, `voices add`, `voices create`,
and `voices prepare`).

## Compatibility rules

- Keep `design` as a supported legacy entry point.
- Preserve existing `synth --voice-id` and `play --voice-id` behavior while the
  normalized family contract is introduced.
- Do not redefine `synth --play` as streaming playback without a separate
  compatibility decision.
- Keep direct C++ executable invocation working for resolved worker paths.
- Keep portable release launchers independent of the developer checkout.

## Verification boundary

Mock workers and deterministic fixtures establish command parsing, normalized
validation, output publication, failure isolation, and portable relocation.
They do not establish GPU quality, real-model voice identity, or listening
acceptance. Those remain separate hardware/model acceptance receipts.

Each implementation PR must report its exact base/head, focused tests, CTest or
Python checks, and any unperformed real-model validation. This document is the
contract owner for command semantics; implementation details belong in the
corresponding Python/C++ modules and tests.
