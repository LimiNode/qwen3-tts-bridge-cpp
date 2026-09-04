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
  -BuildDirectory build/Release `
  -Python py `
  -ModelPath C:/models/Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId my_voice `
  -Text "Voice clone smoke test"
```

Do not pass a preset `speaker` together with a Base `voice_id`. Direct
per-request reference audio remains a diagnostic path; applications should use
registered profiles so preparation stays outside request latency.

## CMP 50HX profile

The launcher exposes explicit CMP profiles through `-RuntimeProfile`:

| Profile | Talker capacity | Emission / decoder | Prebuffer | Intended use |
| --- | ---: | --- | ---: | --- |
| `cmp50hx-ultra-low-latency` | 448 | first E3, then E4 / W29 | 1 | shortest bounded assistant/avatar utterances |
| `cmp50hx-low-latency` | 768 | E4 / W33 | 1 | bounded short assistant/avatar utterances |
| `cmp50hx-safe` | 2048 | E8 / W33 | 1 | long or unknown-length text |

Both profiles use the same persistent worker and registered Base voice. Profile
selection happens when the worker starts; a running FasterQwen model owns one
static Talker graph and cannot safely change `max_seq_len` or its CUDA graph in
the middle of a request. Applications that need to switch profiles while
running should keep two preconfigured clients/workers and route each new
request at a request boundary. Never migrate an in-flight request.

Example low-latency Kraftwerk playback:

```powershell
scripts/start-qwen-tts-clone-play.ps1 `
  -BuildDirectory build/Release `
  -Python py `
  -RuntimeProfile cmp50hx-low-latency `
  -VoiceRegistryPath config/voice-profiles.local.json `
  -VoiceId kraftwerk_robot_ru_bootstrap_fidelity `
  -Text "Привет, это проверка голоса Kraftwerk."
```

Use `cmp50hx-ultra-low-latency` in the same command to select the accepted
W448/E3-to-E4/W29 profile. Its measured first PCM is about 0.61 seconds on the
target CMP 50HX, before player/output-device overhead.

The low-latency profile is bounded by `max_seq_len=768`; callers should split
long text or route it to `cmp50hx-safe`. A request that cannot fit the selected
graph must be treated as failed (never as a successful, silently truncated
utterance); the client should then retry it on the safe profile.
The safe profile keeps the larger 2048-position graph and is the fallback for
long or unknown-length utterances. Detailed measurements and parity evidence
are in [CMP E4 throughput research](cmp50hx-e4-throughput-research.md) and
[CMP Base Startup](cmp50hx-base-profile-startup.md). Before release, run the
[profile acceptance matrix](cmp50hx-profile-acceptance.md), including the
Kraftwerk listening check and target-machine VRAM measurement.
The final bounded-graph comparison and rejected optimization results are in
[CMP latency batch research](cmp50hx-latency-batch-research.md).
