# Local Voice Clone

Base Qwen3-TTS models can synthesize speech from a local reference WAV. This
is separate from CustomVoice preset speakers. The production path registers a
reference once, prepares its model prompt during worker startup, and selects it
by a stable `voice_id` for later requests.

## Registry

Copy `config/voice-profiles.example.json` to an ignored local file and keep the
same schema:

```json
{
  "schema_version": 1,
  "voices": [
    {
      "voice_id": "my_voice",
      "reference_audio_path": "C:/voices/reference.wav",
      "reference_text": "Exact transcript of the reference audio.",
      "x_vector_only": false
    }
  ]
}
```

Reference paths may be absolute or relative to the registry file. Use mono WAV
audio with an exact transcript. The worker validates the profile before it
reports ready and reuses the prepared prompt for every request in the same
persistent session.

## Playback smoke

Build `qwen_tts_play`, then run:

```powershell
scripts/start-qwen-tts-clone-play.ps1 `
  -PlayerPath build/Release/qwen_tts_play.exe `
  -PythonPath py `
  -ModelPath C:/models/Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId my_voice `
  -Text "Voice clone smoke test"
```

Do not pass a preset `speaker` together with a Base `voice_id`. Direct
per-request reference audio remains a diagnostic path; applications should use
registered profiles so preparation stays outside request latency.

## CMP 50HX profile

The accepted idle CMP fast-start profile uses the opt-in Base reference-context
bootstrap, right-padded W48 codec decode, fixed E8 emission, and one playback
prebuffer chunk. See [CMP Base Startup](cmp50hx-base-profile-startup.md) for the
measured scope, parity evidence, listening result, and exact launcher command.
