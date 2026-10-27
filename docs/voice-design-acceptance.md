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

## User CLI

An installed portable package exposes `qwen-tts`. If the exact VoiceDesign
checkpoint is already beside the package under `models/` or in the Hugging
Face cache, no initialization or model path is required:

```powershell
qwen-tts design `
  --text "Привет! Я рада тебя видеть." `
  --instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  --out D:\VoiceDesign\soft-female-ru.wav `
  --play
```

An explicit path always wins and is never silently replaced:

```powershell
qwen-tts design `
  --model D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign `
  --text "Привет!" `
  --instruction "Низкий спокойный мужской голос" `
  --out D:\VoiceDesign\low-male-ru.wav
```

Model management is explicit. Downloads never happen as a side effect of
`design`:

```powershell
qwen-tts models list
qwen-tts models verify voice-design
qwen-tts models download voice-design
qwen-tts models download voice-design --portable
qwen-tts models download voice-design --to D:\Models
```

Resolution precedence is: explicit `--model`, user config, the installed
package's adjacent `models/` directory, then the standard Hugging Face cache.
The cache resolver honors `HF_HUB_CACHE`, then `HF_HOME`, then
`~/.cache/huggingface/hub`; it resolves `refs/main` to an exact snapshot and
refuses ambiguous unreferenced revisions. Incomplete downloads and model-family
mismatches fail closed. If no model exists, the error names the exact explicit
download command.

Custom locations and native GGUF profiles may be stored in a user config based
on `config/qwen-tts.example.json`. `qwen-tts init` is not required. Native
profiles retain explicit runtime, Talker GGUF, codec GGUF, and optional SHA-256
fields; the Python Hugging Face directory contract is never applied to them.

## Low-level acceptance wrapper

The checked PowerShell wrapper remains available for acceptance automation and
direct worker diagnostics. It is not the primary user CLI:

```powershell
.\scripts\start-voice-design-save-wav.ps1 `
  -SaveWavExecutable .\build\default\Release\qwen_tts_save_wav.exe `
  -Worker .\dist\QwenTTSBridge\worker\qwen_tts_worker.exe `
  -WorkerArgument @("qwen", "--model-path", "D:\Models\Qwen3-TTS-12Hz-1.7B-VoiceDesign") `
  -Text "Привет! Я рада тебя видеть." `
  -Instruction "Мягкий, спокойный женский голос с естественной артикуляцией." `
  -Language Russian `
  -Output D:\VoiceDesign\acceptance.wav `
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
