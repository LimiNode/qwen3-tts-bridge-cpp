# Model location contract

The native and Python playback launchers accept model paths outside the
application directory. Relative model paths are resolved from the selected
model root; absolute paths are used as-is.

For both launchers, the current precedence is:

1. explicit CLI path (`-TalkerModel`/`-CodecModel` or `-ModelPath`);
2. explicit CLI `-ModelRoot`;
3. `model_root` in the launcher config;
4. `QWEN_TTS_MODEL_ROOT` environment variable;
5. bundle/repository root for the existing relative-path defaults;
6. the Python launcher’s existing Hugging Face cache fallback when no path is configured.

Native example:

```json
{
  "model_root": "D:/AI/Models/QwenTTS",
  "talker_model": "base/talker-Q8_0.gguf",
  "codec_model": "common/tokenizer-Q8_0.gguf"
}
```

The native launcher also accepts direct overrides:

```powershell
$env:QWEN_TTS_MODEL_ROOT = 'D:\AI\Models\QwenTTS'
scripts\start-native-play.ps1 `
  -TalkerModel 'ru-stress/talker-Q8_0.gguf' `
  -CodecModel 'common/tokenizer-Q8_0.gguf'
```

No model is downloaded by this location contract. Native download remains
controlled by the existing explicit URL and SHA-256 configuration in
`model_download`.
