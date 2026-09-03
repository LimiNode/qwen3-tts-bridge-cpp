# CMP 50HX Base Profile Startup Investigation

## Scope

The supported product path for cloned voices is a registered Base `voice_id`.
Sending a reference WAV with every request is diagnostic-only and is not part of
this investigation.

The current CMP 50HX low-latency configuration is FasterQwen with the
reference-context bootstrap, right-padded codec decode at window `33`, its
manual codec CUDA Graph, `emit_every_frames=8`, and a one-chunk WaveOut
prebuffer. The fixed `E8 + W33 + prebuffer=1` profile is the accepted baseline:
first PCM is about `988 ms` and the bounded starvation proxy is `0`.

The older W48/E16 and `8,23` measurements below are retained as historical
comparators. They are not the selected low-latency profile.

The consolidated production bridge pins FasterQwen commit
`c2c271340d65cd3e9e6d36d9d75af4b57de510f9`, which is reachable from the
current FasterQwen `main` and contains the Base reference-context decoder fix.
When `emit_chunk_schedule` is non-empty it is authoritative: the codec input
bound uses its largest entry. `emit_every_frames` is used only when no schedule
is configured.

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

## Fast-start parity result

The missing Base fast-start comparison was run on an idle CMP 50HX on
2026-09-02. All current-runtime arms used the same 1.7B Base model, prepared
`kraftwerk_robot_ru_bootstrap_fidelity` voice, fixed seed `20260806`, long
Russian request, selected-profile full-EOS warmup, and FasterQwen revision
`19747d4aeba6bbc4ea7d44d5f7ff517fdfba1173`. The reference-context candidate
adds the patch now published as `f1783951f086c94c8a8042d7cce434710819b6b4`.
Both used the 48-frame right-padded codec decoder and its CUDA Graph. Only the
emission and WaveOut prebuffer policies differed in the initial parity pair.

| Profile | First PCM | WaveOut start | Audio | Synthesis | RTF | Later-chunk proxy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| low latency: fixed `E8`, prebuffer 1 | `1552 ms` | `1636 ms` | `19.332 s` | `26.851 s` | `1.389` | `31/31` |
| continuous: `8,23`, prebuffer 2 | `1574 ms` | `4508 ms` | `19.708 s` | `21.309 s` | `1.081` | `0/11` |

Fixed `E8` is not a marginal miss. WaveOut began after the first chunk, but
the queue was empty before every later chunk. Early inter-arrival gaps were
about `1.86-1.91 s`; after calibration, a typical chunk carried about
`619 ms` of audio but arrived every `663-684 ms`. The whole request also ran
slower than realtime, so a one-chunk reserve cannot make this cadence
continuous on the measured runtime.

The `8,23` arm preserves the same roughly `1.57 s` first-PCM latency but waits
for the second chunk before starting WaveOut. It had no later-chunk proxy
observation and at least `639 ms` of queued audio before a later arrival. The
larger steady chunks also reduced generation time by about `5.54 s`; the
prebuffer is therefore hiding a much smaller early deficit rather than fixing
the producer by itself.

An additional compatibility control reproduced the older RTX-era FasterQwen
revision `e4ac767277aad59095122cada01b174fbbb4f429` with its fixed Base
`chunk_size=8`, BF16, 80-frame decoder window, prebuffer 1, and a bounded
two-chunk selected-profile warmup. CMP-specific numerical and right-padded
codec overrides were cleared. That control was worse: first PCM `6198 ms`,
WaveOut start `6268 ms`, `18.493 s` of audio generated in `57.087 s`
(`RTF 3.087`), and `29/29` later-chunk proxy observations. The bridge needed a
temporary compatibility omission of the newer `chunk_schedule` keyword while
running this old revision; the edit was restored immediately after the run.

The result closes the original evidence gap for this hardware and request:
the old RTX-style profile is not a viable continuous-playback mode on CMP
50HX, and restoring the old FasterQwen commit does not help. It also sharpens
the latency statement: roughly four and a half seconds is not a hardware
minimum for *audible onset*--fixed `E8` can start near `1.64 s`--but the tested
fast start starves systematically. Keep the low-latency profile diagnostic and
default-off; retain `8,23` plus prebuffer 2 as the continuous candidate until a
producer-throughput improvement passes the same long-request gate.

## Reference-context bootstrap experiment

The fixed-`E8` failure above exposed a Base-specific decoder integration gap.
The worker captured the 48-frame right-padded codec CUDA Graph, but Base voice
clone streaming stayed on its older accumulated decoder path. Every request
decoded the large reference-code prefix again while deriving a local
`samples_per_frame` estimate. The tested profile contains `227` reference
codec frames, so the fixed graph was captured but could not be used by that
path. RTX 4090 had enough decoder throughput to hide more of this repeated
work; the CMP 50HX crossed the playback deadline.

A default-off FasterQwen experiment now bootstraps Base decoding from the last
25 precomputed reference codec frames. Each fixed-`E8` iteration decodes
exactly `25 + 8 = 33` causal frames in the right-padded 48-frame CUDA Graph and
returns the final eight frames' `640 ms` PCM interval. It does not alter talker
sampling, the prepared voice prompt, or codec-token generation.

The same fixed-seed long request produced the following idle results:

| Path | First PCM | WaveOut start | RTF | Later-chunk proxy |
| --- | ---: | ---: | ---: | ---: |
| accumulated Base baseline | `1552 ms` | `1636 ms` | `1.389` | `31/31` |
| reference bootstrap, three fresh workers | `1004-1006 ms` | `1068-1070 ms` | `1.022-1.028` | `0/31` in all three |
| reference bootstrap, 66.72-second response | `1005 ms` | `1071 ms` | `1.007` | `0/104` |

The 66.72-second response completed with natural EOS after `834` codec frames.
Its synthesis time was `67.205 s`; the reported aggregate RTF includes the
roughly one-second request-to-first-PCM interval, while subsequent 640-ms
chunks normally arrived in about 637-642 ms. One repeated run tolerated a
710-ms scheduling spike using reserve accumulated by earlier chunks.

An idle multi-text gate then sent five sequential requests through one
persistent worker after one bounded, two-chunk selected-profile warmup. The
worker was not restarted between rows:

| Request shape | First PCM | Audio | Completion | Aggregate RTF |
| --- | ---: | ---: | ---: | ---: |
| very short Russian reply | `1001 ms` | `1.20 s` | `1.58 s` | `1.315` |
| Russian date, time, numbers, and punctuation | `999 ms` | `12.32 s` | `12.78 s` | `1.037` |
| conversational Russian response | `1006 ms` | `16.08 s` | `16.57 s` | `1.031` |
| mixed Russian/English identifiers | `1005 ms` | `12.56 s` | `12.95 s` | `1.031` |
| short Russian reply after the mixed request | `1006 ms` | `3.60 s` | `4.01 s` | `1.114` |

All five requests completed. First PCM stayed within `999-1006 ms`, including
the final request, so this run found no request-to-request startup drift or
state-reset failure. Aggregate RTF includes the initial roughly one-second
latency and is therefore not a playback-starvation measure for the two short
utterances. Physical playback stability remains established by the separate
short, medium, repeated, and 66.72-second WaveOut runs above.

The fixed-seed PCM gate preserved all `249` generated codec frames, codec hash
`70468967db173ca2de43e5f1c9aa2ad8058c006ad1daeee899b33c531e6b2530`, and
natural EOS. The candidate emits the complete frame-aligned duration
(`19.920 s` rather than `19.332 s`). Its largest measured sample jump at a
chunk boundary was `0.047`, versus `0.124` for the accumulated baseline.

A manual A/B listening review on 2026-09-02 provisionally accepted the
candidate. The baseline had barely audible loop/splice-like clicks; the
candidate did not reproduce that splice character. Its remaining occasional
ticks were judged to belong to the synthesized signal rather than PCM joins.
The reviewer described the candidate as nearly clean (approximately 99.9%)
and otherwise sounding good. The ignored local listening files are
`tmp/cmp50hx-base-bootstrap-pcm-parity/baseline-listen.wav` and
`candidate-listen.wav`.

Torch `matmul_precision=high` must not be bundled with this candidate. In its
one controlled run it worsened RTF to `1.042` and produced four later-chunk
proxy observations, while leaving the generated codec hash unchanged.

The experiment is exposed through
`-BaseReferenceContextBootstrap` on the CMP playback launcher. It remains
default-off and requires `-CodecRightPaddedDecode`; unsupported or too-short
reference-code histories fail closed. The current idle-CMP acceptance scope is
now passed: varied text, persistent-worker state reuse, short through extended
playback, natural EOS, PCM parity, and listening have all been covered. A
representative LLM/avatar load gate is explicitly deferred until that workload
exists; it is not a prerequisite for using the explicit idle CMP 50HX profile.
Keep the experimental switch default-off until that profile is deliberately
integrated into the release configuration.

```powershell
.\scripts\run-cmp50hx-playback-etw-soak.ps1 `
  -BaseReferenceContextBootstrap `
  -EmitEveryFrames 8 `
  -PlaybackPrebufferChunks 1 `
  -CodecRightPaddedDecode `
  -CodecRightPaddedCudaGraph `
  -CodecRightPaddedWindowFrames 48 `
  <other Base profile arguments>
```

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
