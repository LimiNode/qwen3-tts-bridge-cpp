# Model location contract

The native and Python playback launchers accept model paths outside the
application directory. Relative model paths are resolved from the selected
model root; absolute paths are used as-is. A profile path must not repeat the
model-root directory name (for example, use `ru-stress/file.gguf` with
`model_root: "models"`, not `models/ru-stress/file.gguf`).

The model path and model root precedence are separate.

Model paths use:

1. explicit CLI path (`-TalkerModel`/`-CodecModel` or `-ModelPath`);
2. selected profile path;
3. top-level config path when no named profile is selected;
4. the Python launcher’s existing Hugging Face cache fallback when no path is configured.

Relative paths use this root precedence:

1. explicit CLI `-ModelRoot`;
2. selected profile `model_root`;
3. top-level config `model_root`;
4. `QWEN_TTS_MODEL_ROOT`;
5. bundle/repository root.

Native example:

```json
{
  "model_root": "D:/AI/Models/QwenTTS",
  "talker_model": "qwen-talker-1.7b-base-Q8_0.gguf",
  "codec_model": "common/qwen-tokenizer-12hz-Q8_0.gguf"
}
```

The native launcher also accepts direct overrides:

```powershell
$env:QWEN_TTS_MODEL_ROOT = 'D:\AI\Models\QwenTTS'
scripts\start-native-play.ps1 `
  -TalkerModel 'ru-stress/qwen-talker-1.7b-ru-stress-Q8_0.gguf' `
  -CodecModel 'common/qwen-tokenizer-12hz-Q8_0.gguf'
```

No model is downloaded by this location contract. Native download remains
controlled by the existing explicit URL and SHA-256 configuration in
`model_download`.

## Named model profiles

The native config can select a named split-model pair, while the Python
launcher accepts the same shape with a directory in `model_path`:

```json
{
  "default_model_profile": "ru-stress",
  "model_profiles": {
    "base": {
      "talker_model": "qwen-talker-1.7b-base-Q8_0.gguf",
      "codec_model": "common/qwen-tokenizer-12hz-Q8_0.gguf"
    },
    "ru-stress": {
      "model_root": "D:/AI/Models/QwenTTS",
      "model_path": "ru-stress",
      "talker_model": "ru-stress/qwen-talker-1.7b-ru-stress-Q8_0.gguf",
      "codec_model": "common/qwen-tokenizer-12hz-Q8_0.gguf",
      "experimental": true,
      "text_render_capability": "explicit_combining_stress"
    }
  }
}
```

Select a profile explicitly with `-ModelProfile ru-stress` in the native
PowerShell launcher. An explicit model path still wins over the profile, and
an unknown explicitly requested profile fails closed. Once a named profile is
selected, its required model identity is complete: native profiles must define
both `talker_model` and `codec_model` (unless the corresponding CLI override is
supplied), and Python profiles must define `model_path` (unless `-ModelPath` is
supplied). The standalone C++ example utilities intentionally expose the
smaller worker/frontend surface; a full `--model-profile` C++ CLI remains an
R2 task and is not implied by this R1 configuration contract.

Download metadata is profile-owned as well. A selected native profile uses only
its own `model_download`; top-level `model_download` is used only when no named
profile is selected. A missing profile artifact without profile-owned URL and
SHA-256 fails closed instead of borrowing another profile's identity.

The R1 native example selects `ru-stress` by default. Its
`text_render_capability` is metadata for the application composition layer:
when that profile is selected, construct `TtsFrontTextPreparer` with
`TextRenderCapability::ExplicitCombiningStress`. The native launcher does not
infer stress from filenames. `--no-tts-front` disables preparation explicitly;
selecting `base` keeps the renderer model-neutral and never adds combining
marks. The `ru-stress` default remains conditional on the documented R1
listening and hardware acceptance gates.
