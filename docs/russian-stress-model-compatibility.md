# Russian stress-model compatibility

This note records the bounded compatibility audit for
[`sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf`](https://huggingface.co/sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf).
The audit is informational and does not change the accepted Python worker or
the native production defaults.

## Source and stress contract

The repository was inspected at revision
`e644ae00257fdd4db0e51b11057370dff6be8bc2` (2026-09-24). Its `stress.json`
describes the contract as a combining acute accent, U+0301, placed after the
stressed vowel. The model does not mark `ё` separately. The intended renderer
input therefore contains real UTF-8 combining marks, not transliteration or a
PowerShell code-page approximation.

## Native format result

The current native worker accepts two explicit files:

```text
--talker-model <talker GGUF>
--codec-model  <codec/tokenizer GGUF>
```

The stress repository contains talker/predictor GGUF artifacts, but its codec
side is published as ONNX (`qwen3_tts_decoder.fp16.onnx` and encoder files).
A standalone predictor GGUF is not a replacement for the codec GGUF expected by
the qwentts split runtime. Consequently this repository is currently **not** a
native split-GGUF-compatible model package:

```text
native_split_gguf_compatible = false
```

Do not rename or substitute the ONNX decoder as a `.gguf`, and do not replace
the production codec model. Supporting this format requires a separate engine
integration and its own quality, latency, EOS, and voice-identity gates.

Run the offline audit against a locally downloaded directory with:

```powershell
python scripts/audit-russian-stress-model.py `
  --model-dir E:\models\qwen3-tts-ru-stress `
  --repo-id sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf `
  --revision e644ae00257fdd4db0e51b11057370dff6be8bc2 `
  --hash-files `
  --output docs\reports\russian-stress-compatibility.json
```

The command never downloads files. It reports GGUF magic/version, filename
roles, optional SHA-256 hashes, stress metadata, and explicit blockers. An
incompatible result is a completed audit, not a reason to run an emulated A/B
through the current Base model.

## Deferred A/B plan

If a compatible native split pair becomes available, compare it with the
current Base Q8/Q8 runtime using the same registered voice/reference, seed,
CUDA/runtime build, and text. Keep the exact hashes for both model files and
the runtime manifest. The corpus is:

```text
за́мок / замо́к
му́ка / мука́
а́тлас / атла́с
ко́мпас / компа́с
осу́жденный / осуждённый
обычные предложения без ручного stress
abbreviations после tts-front-cpp
```

Record first PCM, RTF, natural EOS, short/middle/long utterance behavior,
voice identity/timbre, and PCM/WAV hashes. The production default remains
unchanged until those gates pass.
