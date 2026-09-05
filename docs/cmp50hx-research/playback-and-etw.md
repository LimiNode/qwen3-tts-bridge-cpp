# Playback and ETW research

## Scope

PRs #44-#52 investigated whether audible gaps were caused by first-request
graph work, sustained producer throughput, playback reserve, Windows
scheduling, or competing GPU activity. The investigation deliberately used a
WaveOut queue-empty observation as a proxy and did not claim to measure a
physical audio underrun.

## Accepted evidence

The marker-aligned capture `20260816T004412Z-98540` contained no reported event
loss. It recorded eight PCM chunks, 5096.875 ms of audio, seven later queue
empty observations, and eight expected versus twelve observed PerfInfo marks.
The seven inter-arrival intervals were approximately 1317, 1965, 1259, 1840,
716, 695, and 704 ms for chunks containing about 640 ms of audio.

Both the TTS worker and the simultaneous RAG/materializer process had DxgKrnl
activity in every bounded marker window. That established competing GPU
contexts but did not measure execution duration or prove preemption. Replaying
the ETL found zero pairable worker DmaPacket Start/Stop lifecycle records, so
event counts were not converted into GPU durations.

## Controlled results

| Candidate | First playback / RTF | Proxy result | Conclusion |
| --- | --- | ---: | --- |
| E8 baseline | first worker/player audio about 17.96/18.46 s | 7 | Graph capture plus repeated steady gaps |
| Selected-profile warmup, E8 | first player audio about 1.24 s | 6 | Startup improved, sustained issue remained |
| Warmup, E16 | RTF 1.619 in representative-load run | 3 | Insufficient reserve and sub-real-time producer |
| Warmup, E32 | first WaveOut 3514 ms; RTF 1.300847 | 1 | Fewer bursts, unacceptable start and throughput |
| Matmul `high` / TF32 | 7152.027 ms vs 7500.108 ms; RTF 1.425594 | 3 | 4.64% directional gain, not a realtime fix |
| Client AboveNormal | RTF 1.386561 vs 1.386605 | 3 vs 3 | Worker priority attribution not established |
| Full-EOS warmup | initial 0/3, later terminal failures | variable | Dynamic terminal shape remained cold |
| Two-chunk prebuffer | sink start 2718-2737 ms | 0/3 | Effective reserve with explicit start penalty |

The final fast-start profiles returned to one-chunk prebuffer only after codec
and generation throughput improved enough to keep the proxy at zero on the
idle CMP 50HX.

## Reproduction contract

The canonical launcher remains `scripts/run-cmp50hx-playback-etw-soak.ps1`.
An ETW run must be elevated and must not use PCM capture or generation tracing.
A bounded non-ETW experiment may pass `-SkipEtwFollowup`, but its result must
never be cited as ETW evidence.

Representative diagnostic shape:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -PlayerPath build\Release\qwen_tts_play.exe `
  -PythonPath py `
  -ModelPath C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config\voice-profiles.local.json `
  -VoiceId <registered-voice> `
  -WorkerSynthesisWarmup -Attempts 3
```

Exact historical commands and WPR gates are retained in
[the full playback investigation](../cmp50hx-playback-investigation.md#reproduction-examples).
