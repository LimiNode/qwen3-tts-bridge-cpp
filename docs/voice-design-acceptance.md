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

## Reproducible WAV smoke test

Build `qwen_tts_save_wav`, select a compatible VoiceDesign worker/model, and
run the checked wrapper:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker .\dist\QwenTTSBridge\worker\qwen_tts_worker.exe `
  -WorkerArgument @(
      "--engine", "qwen",
      "--model-path", "D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
  ) `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  -Language Russian `
  -Output .\artifacts\voice-design-python.wav `
  -RequireNaturalEos
```

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
