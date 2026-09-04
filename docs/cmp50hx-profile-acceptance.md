# CMP 50HX profile acceptance

This is the release gate for the four explicit 1.7B Base profiles. It must be
run on the target CMP 50HX with the same FasterQwen revision and model/voice
registry used by the deployment.

## Profiles

* `cmp50hx-fastest-experimental`: the ultra graph plus per-registered-voice
  prefix-KV reuse. This is an opt-in perceptual-risk profile and is not required
  to preserve codec/PCM byte parity.
* `cmp50hx-ultra-low-latency`: first E3 then E4, W29, one playback prebuffer,
  `max_seq_len=448`. Use only for the shortest bounded utterances.
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
| registered voice A -> B -> A | A's final request reports A's cache hit; no identity leakage from B |
| registered voice prompt changed under the same ID | prefix mismatch is reported and the cache entry is rebuilt |

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
EOS, and cancellation/reset success. The ultra, low, and safe profiles also
retain their existing fixed-seed codec/PCM comparison. The fastest experimental
profile intentionally changes the autoregressive trajectory, so its gate is the
correct phrase, retained voice identity, and no audible regression such as
clicks, pauses, clipping, corrupted endings, or materially worse pronunciation.
Listening is therefore a required gate for that profile, not just a complement
to byte parity.

## Measured acceptance result

Target run: 2026-09-04, idle CMP 50HX 20 GiB, registered 1.7B Base Kraftwerk
profiles, FasterQwen commit `9a3ee431c0c077e8a67fa2d0a6fe01f198b0cdbf`.

| Profile / case | First PCM | Audio | Cadence | Starvation | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| fastest experimental, fresh warmed workers | 521.2–523.4 ms | 7.36 s / 24 chunks | median 280.8 ms, max 282.9 ms | 0 | phrase/identity gate pending listening |
| low, English long | 675.8 ms | 18.24 s / 57 chunks | median 309.6 ms, max 313.8 ms | 0 | natural EOS |
| low, Russian long | 677.7 ms | 14.08 s / 44 chunks | median 311.4 ms, max 316.6 ms | 0 | natural EOS |
| safe, English long | 970.8 ms | 14.24 s / 23 chunks | median 605.3 ms, max 613.5 ms | 0 | natural EOS |
| safe, Russian warm voice | 973.1 ms | 8.56 s / 14 chunks | median 599.5 ms, max 605.4 ms | 0 | natural EOS |

Two persistent-worker multilingual soaks then completed 30/30 requests each.
The low profile covered RU/EN short and medium cases with first PCM median
`677.8 ms`, p95 `700.5 ms`, and max `717.3 ms`. The safe profile covered the
same matrix with median `971.5 ms`, p95 `980.2 ms`, and max `984.9 ms`. Every
request produced PCM; neither worker restarted.

The lifecycle sequence `complete -> cancel after first PCM -> complete` passed
on one low worker. Cancellation reached its terminal event in `1.54 ms`, and
the post-cancellation request completed. A preliminary human listening check
reported fast subjective startup and clearly retained Kraftwerk identity,
including interactive switching to the warm voice. Chunk-boundary click and
tail ratings remain a human release-note item rather than an automated claim.

Raw-PCM boundary analysis found no systematic splice discontinuity. The
largest boundary delta was `2624` for low/English, `2431` for low/Russian, and
`1580` for safe/English, while the largest ordinary adjacent-sample deltas in
the same captures were respectively `6892`, `4900`, and `8034`. One boundary
in each low capture exceeded that capture's global p99.9 adjacent delta; none
did in safe/English. These isolated values are below ordinary in-signal maxima
and do not by themselves indicate a repeated chunk-join click.

### Capacity behavior

A 216-word Russian boundary request demonstrated why the profiles must remain
explicit. On W768 it produced 531 codec frames / 42.48 seconds of PCM and hit
`max_seq_len`; on W2048 the identical request reached natural EOS after 1612
frames / 128.96 seconds. The worker now fails the W768 terminal state with
`resource_error / sequence_capacity_exceeded` instead of reporting a silently
truncated completion. Named CMP profiles enable generation tracing so this gate
is active in normal launcher use.

This error is necessarily detected at the generation boundary, after already
streamed PCM. A product router should therefore choose the safe worker or split
known-long text before submission; it should not play 42 seconds and then retry
the whole request. The launcher's independent 30-second safety limit still
applies, so very long assistant responses should be split even on the safe
profile.

### VRAM

One warmed low worker used `5944 MiB` at the GPU level. Keeping warmed low and
safe workers alive simultaneously used `11881 MiB` total on the CMP 50HX. The
driver did not expose per-process memory under Windows (`[N/A]`), but both PIDs
were present and process-local low-worker telemetry reported approximately
`5.10 GiB` allocated, `5.52 GiB` reserved, and `6.50 GiB` peak reserved.

Dual-worker request-boundary routing therefore fits the 20 GiB card with about
8.4 GiB remaining, but it does not fit a 10 GiB budget. These figures include
both warmed static graphs and CUDA contexts.

Raw reports and PCM captures are under
`tmp/cmp50hx-profile-acceptance/` and are intentionally unversioned.

## Ultra profile addendum

The follow-up latency batch accepted `cmp50hx-ultra-low-latency` on the same
CMP 50HX. Three fresh workers measured `606.0-608.3 ms` first PCM, about
`282.9-285.1 ms` median cadence, and zero starvation. A 30-request persistent
RU/EN soak completed 30/30 with `610.901 ms` median, `614.177 ms` p95, and
`617.460 ms` maximum first PCM. Cancellation/reset and a 12.88-second natural
EOS request passed. See [CMP latency batch research](cmp50hx-latency-batch-research.md)
for the full matrix, W384 capacity rejection, async-codec result, and failed
prefix-KV parity experiment.

Automated PCM-boundary analysis found no W29 splice signature, but human
listening to the W29 output remains the final subjective release gate.
