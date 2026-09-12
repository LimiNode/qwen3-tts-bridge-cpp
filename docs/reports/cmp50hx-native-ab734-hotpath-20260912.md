# CMP 50HX native hot-path characterization — 2026-09-12

This report records the first run with the freshly rebuilt qwentts runtime at
`ab73452` (qwentts PR #6 merge), compiled for the host GPU's compute capability
7.5. It is characterization evidence, not release acceptance: semantic audio
quality, duration, and voice identity still require a listening/quality gate.

## Environment

| Field | Value |
| --- | --- |
| GPU | NVIDIA CMP 50HX, 20 GiB, compute capability 7.5 |
| Driver | 581.94 |
| qwentts runtime | `ab73452` / ABI 5 / CUDA / `sm_75` |
| Talker | `qwen-talker-1.7b-base-Q8_0.gguf` |
| Codec | `qwen-tokenizer-12hz-Q8_0.gguf` |
| Voice mode | registered Base profile, preloaded reference |
| Stream cap | one codec frame (`--stream-max-chunk-frames 1`, 80 ms PCM) |

The runtime directory, manifest, models, registry, and raw JSON artifacts are
machine-local and intentionally remain outside git:

```text
C:\tmp\qwentts-native-runtime-ab734-cmp75
C:\tmp\native-cmp50hx-registry-ru.json
C:\tmp\native-cmp50hx-base-registered-ab734-probe.json
C:\tmp\native-cmp50hx-base-registered-ab734-30req.json
```

## Native registered-voice result

The single probe passed every automated gate: ready handshake, warmed state,
registered voice cache hit, non-empty PCM, natural EOS, and no starvation.

The 30-request sequential soak passed protocol/transport/terminal acceptance
for all 30 requests with no failures, cancellations, acceptance failures, or
starvation events. This is not a semantic TTS acceptance result: the short
text produced an invalidly long output before the reference-boundary fix.

| Metric | Value |
| --- | ---: |
| First PCM minimum | 179.696 ms |
| First PCM median | **182.451 ms** |
| First PCM p95 | 186.85 ms |
| First PCM maximum | 190.017 ms |
| Completion median | 12,820.794 ms |
| Completion p95 | 13,033.649 ms |
| RTF median | 0.313 |
| Protocol/transport/terminal acceptance | 30/30 |

The qwentts phase metrics in the single probe reported approximately 178 ms
TTFA and 161 ms prefill. The first PCM signal was non-empty (`s16_rms` about
233), and the registered reference was a cache hit (`voice_reference_extract_ms`
was zero on the measured request).

## Important semantic blocker

The short test text produced about 512–517 codec frames (roughly 41 seconds of
PCM) before natural EOS. This is not an acceptable user-facing duration for the
short sentence and has not been validated for pronunciation or voice identity.
The latency result is therefore a first-PCM characterization only; it must not
be presented as release-quality TTS acceptance until the output-duration and
listening gates pass.

## Faster registered profile comparison

An isolated Faster `cmp50hx-fastest` run was also attempted with the exact
profile controls (right-padded decode window 29, E3/E4 schedule, CUDA graphs,
FP32 MLP island, and registered voice). Its first PCM was about 0.60 s after
the profile graphs were captured, but the request terminated with
`max_seq_len` and the benchmark rejected it fail-closed. The run is not a
successful baseline and is retained only as diagnostic evidence:

```text
C:\tmp\cmp50hx-fastest-registered-20260912-final.json
```

The earlier no-optimization debug run (about 9.6 s first PCM) is not a
`cmp50hx-fastest` result and is not used for comparison.

## Next gates

1. Diagnose native long-output/quality behavior on the same Base GGUF and
   reference profile; capture WAV and listen before claiming voice parity.
2. Fix or explicitly bound the Faster profile's `max_seq_len` outcome while
   preserving its first-chunk target.
3. Rerun the direct-reference native-vs-Faster matrix with a valid direct
   reference warmup request shape, then run the registered Faster baseline
   separately.
4. Only after duration, pronunciation, voice identity, cancellation, and
   restart/recovery gates pass should these measurements become release
   acceptance evidence.
