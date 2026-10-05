# Russian stress-model compatibility

This note records the bounded compatibility audit for
[`sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf`](https://huggingface.co/sknyazev/qwen3-tts-12hz-1.7b-ru-stress-gguf).
The audit is informational and does not change the accepted Python worker or
the native production defaults.

## Source and stress contract

The repository was inspected at revision
`e644ae00257fdd4db0e51b11057370dff6be8bc2` (2026-09-24). Its `stress.json`
describes the contract as a combining acute accent, U+0301, placed after the
stressed vowel. The model does not mark U+0451 (`ё`) separately. The intended renderer
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
the qwentts split runtime. The published package is not directly consumable by
the native split loader. The supported research path is to merge the published
LoRA into the exact Base talker checkpoint and run the pinned qwentts converter
with the official Base 12-Hz tokenizer.

The conversion proof is recorded in
[`docs/reports/russian-stress-native-conversion.json`](reports/russian-stress-native-conversion.json).
It produced a native talker/codec pair outside the repository and a CPU load
and synthesis receipt. The pair is experimentally load-compatible, but it is
not yet a supported model profile: target-hardware latency, voice identity,
EOS, and listening gates remain open.

The merge step is intentionally an explicit research command and requires
PyTorch plus `safetensors` in the research environment:

```powershell
python scripts/merge-russian-stress-lora.py `
  --base-dir E:\models\qwen3-tts-base `
  --adapter-dir E:\models\qwen3-tts-ru-stress\lora `
  --output-dir E:\tmp\qwen3-tts-ru-stress-merged `
  --expected-base-revision fd4b254389122332181a7c3db7f27e918eec64e3 `
  --receipt E:\tmp\qwen3-tts-ru-stress-merge-receipt.json
```

It fails closed on the pinned Base/adapter SHA-256, Base revision, exact 196
LoRA-pair contract, target root, LoRA shapes, and non-zero deltas. The output
directory is converter-ready: alongside the merged `model.safetensors`, the
script copies and hashes `config.json`, `generation_config.json`, `merges.txt`,
`tokenizer_config.json`, and `vocab.json` from that same exact Base directory.
It writes no files under the repository's `models/` directory and does not
alter a bridge profile.

The published package itself remains **not directly split-GGUF-compatible**:

```text
published_package_native_split_gguf_compatible = false
converted_experimental_pair_native_load = true
```

The source package also publishes a standalone predictor GGUF and tokenizer
JSON, but the current bridge loader does not accept a standalone predictor
argument. It requires a talker GGUF plus a codec/tokenizer GGUF. The audit
records this loader contract explicitly rather than inferring compatibility from
the presence of any individual GGUF file.

The source metadata currently identifies the base family as
`Qwen/Qwen3-TTS-12Hz-1.7B-Base`; filenames expose Q5/Q8/F16 variants. The
12-Hz naming and U+0301 convention are provenance facts, not proof that this
ONNX codec stack can be loaded by qwentts.cpp.

The source declares Apache-2.0 licensing and tags the package for
`voicy`, llama.cpp, and ONNX Runtime. The exact source file inventory and
provenance are recorded in
[`docs/reports/russian-stress-source-audit.json`](reports/russian-stress-source-audit.json).
That report intentionally contains no model weights or downloaded artifacts.

Do not rename or substitute the ONNX decoder as a `.gguf`, and do not replace
the production codec model. The conversion script merges only the talker LoRA;
predictor and speaker-encoder tensors are proven unchanged, and the codec is
the official Base tokenizer converted by the pinned qwentts tool. This keeps
the native path free of ONNX runtime dependencies while retaining the source
model's explicit U+0301 stress contract.

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
roles, selected GGUF metadata, tokenizer vocabulary information, optional
SHA-256 hashes, stress metadata, provenance, and explicit blockers. An
incompatible result is a completed audit, not a reason to run an emulated A/B
through the current Base model.

## Deferred A/B plan

The experimental pair must next be compared with the
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
