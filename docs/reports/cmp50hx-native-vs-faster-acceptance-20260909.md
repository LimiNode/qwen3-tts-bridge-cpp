# CMP 50HX native versus FasterQwen acceptance (2026-09-09)

This report records the first hardware run of the native qwentts.cpp worker
against the Python/FasterQwen worker on the same CMP 50HX host. It is a
characterization report, not a release promotion: the native and Python
engines use different model representations and are expected to produce
different PCM trajectories.

## Reproducibility

* GPU 0: NVIDIA CMP 50HX, 20,480 MiB, driver 581.94.
* Bridge: `8cabf015939941a76187d5aff5d91a9b6526e67f`.
* Native qwentts.cpp: `1c119f6` (CUDA, ABI/runtime manifest pinned).
* Native models: external Talker/Base Q8_0 GGUF and 12 Hz tokenizer Q8_0 GGUF.
* Python model: external Qwen3-TTS 1.7B Base safetensors.
* FasterQwen source: external revision `90b596d2ffa41eb2da173db92e6f896df11b19cb`.
* Workload: 10 rows covering Russian/English, short/medium text, A/B/A voice
  switching, capacity boundaries, and cancellation after first PCM.
* Runs used two warmups, ten measured requests, seed policy 4242, and
  `CancelEvery=0`; explicit cancellation is represented by the manifest row.

Raw JSON and per-run evidence remain outside the repository under
`C:\tmp\cmp50hx-native-acceptance\matrix-cmp50hx-full10.json`.

## Results

The persistent native worker passed the short Russian/English and voice-switch
rows, and produced natural EOS for those rows. One English medium row completed
without PCM, so the fail-closed gate rejected it. First-PCM latency on rows
that produced audio was 2.02--3.07 s (median 2.11 s on the ten-row run), with a
5.44 s process/model startup and a system GPU peak of 4,268 MiB. The explicit
cancellation row cancelled after the first PCM as expected.

The Python worker also completed the ordinary rows and cancelled correctly,
but its low-latency run on this host reported a 18.15 s startup and first PCM
of 1.75--2.64 s on ordinary rows. The two long rows hit the FasterQwen sequence
capacity and were reported as `resource_error/sequence_capacity_exceeded`.
Those rows therefore failed the intentionally strict contract instead of
being counted as successful long-text synthesis. System GPU peak was 9,616 MiB.

Native long rows reached `max_tokens` without generation-trace EOS evidence and
were rejected by the same fail-closed gate. This is a real native limitation:
the current qwentts.cpp ABI does not yet expose the Python profile's split/fallback
policy, so long text must be routed or rejected before native generation in a
release configuration.

An additional native A/B with `stream_max_chunk_frames=4` versus `8` (three
short/medium rows, fresh worker each time) showed no meaningful first-PCM
improvement: median 2.130 s versus 2.117 s, respectively. The setting changed
chunk grouping but not the dominant time-to-first-audio path, so it is not a
standalone acceleration candidate on this build.

## Compatibility findings

The launcher-only `--runtime-profile` settings are not sufficient to reproduce
the historical 520--680 ms FasterQwen measurements. The first comparison also
exposed an environment problem: Windows Python was importing a stale per-user
`qwen_tts` package from `%APPDATA%`, whose 12 Hz decoder class lacked
`capture_cuda_graph` and `forward_optimized`. With `PYTHONNOUSERSITE=1`, the
bundled decoder exposes both methods and the right-padded path starts normally.
The acceptance runner now enforces that isolation for Python benchmark and
playback processes.

Even with the correct decoder import, the restored-profile smoke measured about
1.41 s first PCM after one warmup, not the historical ~520 ms. Reproducing that
number still requires the exact voice-prefix warmup/profile artifact used by
the original experiment; it must not be presented as a native-vs-Python result
until that artifact is recovered. The current run remains valuable: it proves
the native worker, provenance capture, EOS/cancellation gates, and cross-backend
lifecycle harness work on real CMP hardware.

### Corrected registered-voice smoke

The launcher was then corrected to make the profile warmup use the same
language as the first request and to export `PYTHONNOUSERSITE=1` while the
worker process is running. A one-shot English request using the registered
`kraftwerk_robot_ru_bootstrap_fidelity` voice, FasterQwen source
`C:\\tmp\\qwen-prefix-reuse-20260904\\faster` at commit
`90b596d2ffa41eb2da173db92e6f896df11b19cb`, right-padded W29/CUDA Graph,
E3-to-E4 schedule, and one warmup produced the following objective result:

```text
first_audio_ms = 524.731
audio_duration_ms = 5920.0
audio_chunks = 19
termination = natural EOS
voice_clone_prompt_source = precomputed
voice_clone_prompt_sha256_before == voice_clone_prompt_sha256_after
```

This reproduces the historical approximately 520--543 ms cache-hit range on
the CMP 50HX. The earlier 1.41 s observation was a cold/mismatched warmup and
must not be used as the restored-profile performance number. The isolated
user-site environment is now enforced by both the acceptance runners and the
interactive launcher.

## Follow-up gates

1. Keep the compatible FasterQwen decoder revision and user-site isolation
   pinned in deployment; the historical low-latency range is now reproduced by
   the registered-voice launcher smoke.
2. Add native profile routing/fallback before accepting long rows; native
   currently supports stream cadence values 1/2/4/8, but not W29/W33, prefix-KV
   reuse, or the Python codec scheduling policy.
3. Run the same matrix on RTX 4090; this host has only a GTX 1060 as GPU 1, so
   no RTX 4090 result is claimed here.
4. Run restart/recovery as a separate lifecycle phase and perform the manual
   playback/listening check after the objective gates pass.
