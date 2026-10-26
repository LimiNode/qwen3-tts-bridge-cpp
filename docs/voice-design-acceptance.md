# VoiceDesign acceptance

This document describes the reproducible VoiceDesign smoke path. It does not
introduce a second synthesis implementation: the existing `qwen_tts_save_wav`
example remains the only WAV writer and the selected worker remains responsible
for model loading and inference.

## Contract

VoiceDesign requests contain:

- spoken `text`;
- a language name;
- a non-empty natural-language `instruction` describing the generated voice.

VoiceDesign does not use a speaker preset, registered Base `voice_id`, or Base
reference-audio fields. The Python worker rejects those fields instead of
silently ignoring them. Streaming is used when the loaded runtime advertises a
VoiceDesign streaming API. A runtime without that capability may use its
full-audio path; that result must not be reported as realtime streaming.

Each VoiceDesign request creates a voice rendition from its `instruction`; it
does not create a persistent `voice_id`. Keep the instruction alongside the
WAV if a rendition needs to be reproduced. Persistent voice profiles are a
separate Base voice-clone feature documented in [docs/voice-clone.md](voice-clone.md).

## Reproducible WAV smoke test

Build `qwen_tts_save_wav`, select a compatible VoiceDesign worker/model, and
run the checked wrapper:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker .\dist\QwenTTSBridge\worker\qwen_tts_worker.exe `
  -WorkerArgument @(
      "qwen",
      "--model-path", "D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
  ) `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  -Language Russian `
  -Output .\artifacts\voice-design-python.wav `
  -RequireNaturalEos
```

For an unpackaged Python worker, use the same wrapper with the Python executable
and the canonical `qwen` subcommand. The wrapper passes each item in
`-WorkerArgument` as one worker argument and restores the caller's environment
after the process exits:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker C:\Python311\python.exe `
  -PythonPath @(
      ".\worker\src",
      ".\external\python\faster-qwen3-tts",
      ".\external\python\Qwen3-TTS-streaming"
  ) `
  -WorkerArgument @(
      "-m", "qwen_tts_bridge_worker", "qwen",
      "--model-path", "D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign",
      "--runtime-backend", "faster",
      "--device", "cuda",
      "--dtype", "auto"
  ) `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной русской артикуляцией." `
  -Language Russian `
  -Output D:\VoiceDesign\soft-female-ru.wav `
  -ResultJson D:\VoiceDesign\soft-female-ru.json `
  -RequireNaturalEos
```

Use `scripts/start-voice-design-play.ps1` when the goal is immediate listening
instead of a WAV file. It uses the same worker/model arguments and opens the
normal `qwen_tts_play` playback path:

For repeated manual experiments, copy
`config/voice-design-runtime.example.json` to the ignored
`config/voice-design-runtime.local.json` and edit the Python, source, build, and
model paths once. Then a listening run only needs the profile, instruction, and
text:

```powershell
Copy-Item config/voice-design-runtime.example.json config/voice-design-runtime.local.json
.\scripts\start-voice-design-play.ps1 `
  -ConfigPath config/voice-design-runtime.local.json `
  -ModelProfile voice-design-1.7b `
  -Instruction "Мягкий, спокойный женский голос с естественной русской артикуляцией." `
  -Text "Привет! Я рада тебя видеть."
```

The explicit form remains available when a local config is not desirable:

```powershell
.\scripts\start-voice-design-play.ps1 `
  -BuildDirectory .\build\default\Release `
  -Python C:\Python311\python.exe `
  -ModelPath D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign `
  -RuntimeBackend faster `
  -Instruction "Мягкий, спокойный женский голос с естественной русской артикуляцией." `
  -Text "Привет! Я рада тебя видеть."
```

The playback launcher resolves the vendored Qwen sources from
`external/python/` by default. If those sources live elsewhere, pass
`-FasterSourcePath` and `-QwenSourcePath` explicitly. For a release package,
point `-Python` at the packaged runtime and keep the model directory external.

Add `-Interactive` to enter several utterances in one persistent worker. In
interactive mode use `/style <text>` to replace the instruction, `/language
<name>` to change language, `/cancel` to cancel the active request, and `/quit`
to stop. The `-NoPlayback` switch is useful for checking the request path
without opening the audio device; it does not save a WAV.

For the native worker, pass its runtime and split model paths as worker
arguments. The exact GGUF conversion and qwentts runtime must be recorded in
the acceptance receipt:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker .\build\native\Release\qwen_tts_native_worker.exe `
  -WorkerArgument @(
      "--runtime-dir", "D:\QwenRuntime",
      "--talker-model", "D:\Models\voice-design-talker-Q8_0.gguf",
      "--codec-model", "D:\Models\qwen-tokenizer-12hz-Q8_0.gguf"
  ) `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  -Language Russian `
  -Output .\artifacts\voice-design-native.wav `
  -RequireNaturalEos
```

The wrapper checks that the command completed, the result JSON reports a
completed request with non-empty audio, and the WAV is PCM16 with the requested
sample rate and channel count. It writes a sibling result JSON unless
`-ResultJson` is supplied explicitly.

Store generated WAVs, receipts, model caches, and runtime logs outside the
repository (for example under `D:\VoiceDesign\`). Do not commit model weights
or private runtime files.

## Acceptance receipt

For each backend, record the exact model revision or GGUF SHA-256, worker and
runtime versions, qwentts/ABI revision when applicable, GPU/device, language,
text, instruction, output WAV metadata, terminal outcome, and wall-clock
generation time. Mark a backend `NOT RUN` when its model/runtime artifacts or
target hardware are unavailable. A local mock-worker run is useful for CLI and
WAV plumbing, but is not a VoiceDesign quality or model-compatibility result.

The current repository does not commit VoiceDesign weights or a native
VoiceDesign GGUF. Therefore a real-model acceptance run is an external,
environment-specific gate rather than a default CI test.
