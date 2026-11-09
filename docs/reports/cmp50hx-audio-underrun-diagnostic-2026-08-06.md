# CMP 50HX audio-underrun diagnostic

> Historical diagnostic summary (August 2026). It records a bounded experiment and is not a current release gate. Raw machine artifacts are intentionally local-only and are not part of this curated documentation set.

Classification: PCM production slower than realtime.

The physical sealed R3 package was not rebuilt or modified. Its marker was
present and package-tree/voice-assets manifests passed before and after the
diagnostic. The verified package digest remained
`c2a5133e843d5660b2fd0ca3c2b633f54154195c6fc1c76e7d0994542211ecfc`.

The source-built latency runner was a diagnostic client only. It launched the
private Python worker from the physical R3 package with package-private
`PYTHONHOME`/`PYTHONPATH`; it did not use a source worker. Policy was FasterQwen
eager prefill with no compile, allowlist, canary, emit schedule, or RTX-4090
8,8,12 profile. `bridge_cuda_graph_control=not_applicable` and
`runtime_internal_cuda_graphs_may_be_enabled=true`.

Each model used one new worker process followed by two same-worker requests for
each short, medium, and long class. No reboot or OS cache reset occurred, so no
OS-cache-cold claim is made.

| Model | First chunk audio | Second PCM arrival gap | Steady RTF | Finding |
| --- | ---: | ---: | ---: | --- |
| CustomVoice | 616.875 ms | 1,154.792–1,187.855 ms | 2.146–2.211 | PCM arrives about twice as slowly as realtime playback needs it. |
| Base fidelity profile | 639.250 ms | 4,043.025–4,095.518 ms | 2.785–8.587 | PCM arrival is far slower than realtime, explaining the audible gaps. |

Process-cold model loads were 23.35 s for CustomVoice and 24.70 s for Base.
They are reported separately from same-worker TTFA: ~1.48–1.59 s CustomVoice
and ~6.15–6.20 s Base.

The runner records monotonic client IPC receive timestamps, every PCM chunk,
chunk duration, request completion, RTF, inverse RTF, and available worker
metrics in local raw JSON artifacts that are intentionally not tracked here. R3 does not expose pull-level audio sink
requests to that runner, so sink consume timestamps, period, queue depth,
low-water marks and true underrun deficit frames are `unavailable`. No event
is counted as an underrun without a sink request with insufficient queued
frames. The production CLI backend is `waveOut/WAVE_MAPPER`; its shared versus
exclusive mode is not exposed by that API.

The current evidence rules out a client playback-queue-only explanation: the
second PCM block arrives after the first block's audio duration for both models.

One safe next CMP-specific A/B experiment: compare FasterQwen eager against the
upstream backend for one already-loaded medium CustomVoice request, holding all
inputs fixed and without compile, CUDA-graph, schedule, canary or allowlist
options.
