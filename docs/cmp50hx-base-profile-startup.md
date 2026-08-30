# CMP 50HX Base Profile Startup Investigation

## Scope

The supported product path for cloned voices is a registered Base `voice_id`.
Sending a reference WAV with every request is diagnostic-only and is not part of
this investigation.

The tested steady-delivery configuration is FasterQwen with right-padded codec
decode at window `48`, its manual codec CUDA Graph, `emit_every_frames=16`, and
a two-chunk WaveOut prebuffer.

## Observed Baseline

On 2026-08-30, the ready Kraftwerk Base profiles completed without later-chunk
WaveOut queue-starvation-proxy observations, but did not have low startup
latency. For `bootstrap_fidelity`, the first PCM arrived at about `2756 ms` and
WaveOut started at `5249 ms`; the second PCM was intentionally required by the
two-chunk prebuffer. The other accepted profiles started the sink in roughly
`4806-5144 ms`.

This is not the same performance contract as the historical RTX 4090 result:
the latter measured the `0.6B` CustomVoice model with an exact compiled-prefill
allowlist and first-chunk startup prewarm. It reached roughly `250–600 ms`
first PCM only after paying a long startup preparation before `ready`. A Base
`1.7B` registered profile has a different prompt and model path, so that number
cannot be transferred without measurement.

## Candidate Fix

The registered profile is prepared and warmed before the worker reports ready,
but a one-run A/B did not improve first PCM (`2722 ms` versus `2745 ms`). The
remaining dominant cost is Base first-window generation. The candidate changes
only the Base emission cadence:

```text
first codec window: 8 frames
subsequent codec windows: 23 frames
```

The initial `8`-frame output cuts first PCM work. The following `23`-frame
value is also the steady cadence: the streaming schedule uses its final value
for later chunks. It restores a roughly `2.48 s` audio reserve before playback;
`25` decoder-context frames plus `23` new frames exactly fit the accepted fixed
`48`-frame decoder window. No raw reference audio is passed per request and the
normal numerical/Faster execution path is not changed. The schedule is
implemented by the pinned FasterQwen fork revision
`19747d4aeba6bbc4ea7d44d5f7ff517fdfba1173`.

The first valid one-attempt comparison reduced first PCM from `2722 ms` to
`1560 ms` and physical WaveOut start from `5194 ms` to `4449 ms`, with zero
later-chunk queue-starvation-proxy observations in both arms. This is promising
but is not a production promotion: it needs the repeated A/B below, PCM/EOS
validation, and listening review.

## PCM and Listening Gate

Do not use byte-for-byte streamed PCM equality as the acceptance gate for a
different Base emission cadence. The codec decoder is evaluated on each
currently available streaming prefix; changing `16,16,...` to `8,23,23,...`
therefore changes decoder-prefix boundaries even when the fixed request seed
and generated codec-token stream are the same. It can change sample values at
those boundaries without changing the requested text, profile, or terminal
generation semantics.

A fixed-seed one-request capture on 2026-08-30 completed in both arms. The
fixed-16 arm produced `250292` bytes (five PCM chunks, about `5.214 s`); the
8,23 arm produced `251300` bytes (four chunks, about `5.235 s`). The `1008`
byte difference is about `21 ms`, so the ordinary exact-PCM comparison tool
correctly rejects it due to unequal sample counts. This is a *pending quality
finding*, not evidence of a crash or a claimed EOS regression.

Before promotion, validate all of the following with the fixed seed:

1. complete generation and an explicit EOS trace in both arms, with matching
   generated codec-token hash and frame count;
2. no later-chunk queue-starvation-proxy observation in repeated idle runs;
3. a short A/B listening check for profile identity, intelligibility, joins,
   and the final tail.

The local listening captures are deliberately generated under `tmp/` and must
not be committed. For the current comparison they are `fixed-16.wav` and
`schedule-8-23.wav` in `tmp/cmp50hx-base-profile-startup-parity/`.

## Long-Response Cadence Boundary

The short startup request is insufficient to assess the initial reserve. A
fixed-seed 26.8-second response was therefore used on the same ready Base
profile. These are single-run research measurements, not release claims:

| Schedule | First PCM | WaveOut start | Later-chunk proxy | Result |
| --- | ---: | ---: | ---: | --- |
| `1,23` | `1108 ms` | `3999 ms` | `2` | rejected |
| `2,23` | `1175 ms` | `4074 ms` | `1` | rejected |
| `6,23` | `1443 ms` | `4399 ms` | `0` | provisional |
| `8,23` | `1559 ms` | `4442 ms` | `0` | current conservative candidate |

`1,23` and `2,23` make the sink start sooner, but the initial audio reserve is
too small for the pre-calibration transition into the first sliding-window
decode. They are rejected even though the rest of the stream subsequently
recovers. `6,23` shows the expected boundary, but its observed margin before
the third chunk is only about `69 ms`; it needs repeated stress validation.
`8,23` had about `222 ms` in this run and is the safer startup-cadence
candidate.

This establishes the limit of cadence-only work: it reduces the physical
Base-profile start from roughly `5.3 s` to roughly `4.4 s`, but it cannot make
the prepared 1.7B Base route genuinely low-latency by itself. The next
performance investigation must reduce the per-request Base talker prefill and
early autoregressive work (with an exact-shape, quality-gated prefill path),
not weaken the two-chunk playback reserve.

## Controlled A/B

Use the dedicated script below on an idle CMP 50HX. It runs fresh workers for
both arms and reports first PCM arrival and physical WaveOut start separately.
Both arms require zero later-chunk queue-starvation-proxy observations; that
proxy is not a hardware-underrun counter.

```powershell
.\scripts\run-cmp50hx-base-profile-startup-ab.ps1 `
  -PlayerPath 'E:\_repoz\qwen3-tts-bridge-cpp\build\cmp50hx-diagnostic-mingw\qwen_tts_play.exe' `
  -PythonPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\QwenTTSBridge-technical-beta-r3\QwenTTSBridge-technical-beta-r3\worker\python\python.exe' `
  -BaseModelPath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-external-models\Qwen3-TTS-12Hz-1.7B-Base' `
  -VoiceRegistryPath '.\config\voice-profiles.example.json' `
  -VoiceId 'kraftwerk_robot_ru_bootstrap_fidelity' `
  -RuntimeCachePath 'E:\_repoz\qwen3-tts-bridge-cpp\tmp\cmp50hx-r3-runtime-cache' `
  -Attempts 3
```

Interpret `median_delta_ms.first_pcm_arrival` and
`median_delta_ms.waveout_start` as `8,23` minus fixed `16`: a negative value is
an improvement. Do not promote the candidate until it improves the observed
latency without a new PCM/EOS, profile-identity, or playback-stability
regression.
