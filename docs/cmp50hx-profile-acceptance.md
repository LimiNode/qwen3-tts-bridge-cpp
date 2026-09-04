# CMP 50HX profile acceptance

This is the release gate for the two explicit 1.7B Base profiles. It must be
run on the target CMP 50HX with the same FasterQwen revision and model/voice
registry used by the deployment.

## Profiles

* `cmp50hx-low-latency`: E4, W33, one playback prebuffer, `max_seq_len=768`.
  Use only for bounded utterances.
* `cmp50hx-safe`: E8, W33, one playback prebuffer, `max_seq_len=2048`.
  Use for long or unknown-length text.

The profile is selected when the worker starts. To switch during service, keep
one persistent worker per profile and route each new request to the appropriate
worker; do not change a graph while a request is running.

## Automated matrix

For each profile, run three fresh workers and then a persistent-worker sequence
containing all of the following cases:

| Case | Required assertion |
| --- | --- |
| short English and Russian | non-empty PCM, natural EOS |
| medium English and Russian | no late queue starvation |
| long text | low profile is routed to safe (or rejected before generation) |
| near capacity | completion is not reported as truncated |
| over capacity | explicit request/model error, never silent success |
| repeated requests (30–100) | no starvation, graph reset and stable EOS |
| cancel after first PCM, then next request | one cancellation terminal event; next request completes |

The existing playback soak runner supplies the objective timing and starvation
proxy. A low-profile run is:

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -PlayerPath build\Release\qwen_tts_play.exe `
  -PythonPath py `
  -ModelPath C:\models\Qwen3-TTS-12Hz-1.7B-Base `
  -VoiceRegistryPath config\voice-profiles.local.json `
  -VoiceId kraftwerk_robot_ru_bootstrap_fidelity `
  -FasterSourcePath C:\src\faster-qwen3-tts `
  -RuntimeCachePath tmp\cmp50hx-runtime-cache `
  -EmitEveryFrames 4 -MaxSeqLen 768 `
  -CodecRightPaddedDecode -CodecRightPaddedCudaGraph `
  -CodecRightPaddedWindowFrames 33 `
  -BaseReferenceContextBootstrap `
  -PlaybackPrebufferChunks 1 -WorkerSynthesisWarmup `
  -WorkerWarmupVoiceId kraftwerk_robot_ru_bootstrap_fidelity `
  -Attempts 3 -SkipEtwFollowup
```

Repeat with `-EmitEveryFrames 8 -MaxSeqLen 2048` for the safe profile. The
launcher provides the same settings more conveniently for a one-shot listening
test:

```powershell
.\scripts\start-qwen-tts-clone-play.ps1 `
  -RuntimeProfile cmp50hx-low-latency `
  -VoiceRegistryPath config\voice-profiles.local.json `
  -VoiceId kraftwerk_robot_ru_bootstrap_fidelity `
  -Text "Привет, это проверка голоса Kraftwerk."
```

Listen for clicks at chunk boundaries, pauses, clipping, changed word endings,
and a clipped EOS. Record the generated WAV/metrics path and the profile name.
Objective promotion gates are zero later-chunk starvation observations, natural
EOS, cancellation/reset success, and codec-token/PCM parity against the fixed
seed control. Human listening is a complementary playback sanity check.

## Current evidence and remaining hardware check

The bounded E4/W33/768 candidate has already passed the controlled parity pair:
first PCM `677.6 ms`, median cadence `311.4 ms`, starvation `0`, natural EOS,
and byte-identical PCM to the 2048 control. Three additional W768 attempts had
maximum inter-arrival `313.3 ms`; persistent reuse and cancellation/reset also
passed. The safe E8/W33/2048 path remains the fallback.

VRAM usage must still be recorded on the deployment machine for one warm worker
and two simultaneously warm workers. Do not infer this from model parameter
count: static Talker caches and CUDA allocator reserve are included. Capture
`torch.cuda.max_memory_reserved()` and `nvidia-smi` process usage for both
profiles before enabling dual-worker routing.
