# CMP 50HX native warmup probe (2026-09-12)

This is a local hardware characterization, not a release acceptance result.
It records the effect of moving the first qwentts synthesis into worker
startup for a registered Base voice.

## Environment

| Field | Value |
| --- | --- |
| GPU | NVIDIA CMP 50HX, 20 GiB, compute capability 7.5 |
| CUDA driver | 581.94 |
| qwentts runtime | `7dea823` CUDA runtime bundle |
| Talker | `qwen-talker-1.7b-base-Q8_0.gguf` |
| Codec | `qwen-tokenizer-12hz-Q8_0.gguf` |
| Voice | registered `kraftwerk` profile, mono 24 kHz WAV |
| Streaming cap | `--stream-max-chunk-frames 1` (first chunk = 1 codec frame / 80 ms) |
| Request | `Профиль Kraftwerk Robot работает на CMP 50HX.` |

The runtime bundle predates the phase-metrics export from qwentts PR #6, so
phase values below come from the runtime's stderr diagnostics; the Bridge
`qwen_*_ms` JSON fields remain zero for this compatibility run by design.

## Results

| Mode | First PCM | Synthesis total | Notes |
| --- | ---: | ---: | --- |
| cold worker, registered voice preloaded | 1,444–1,458 ms | about 1,865 ms | lazy codec load and CUDA graph capture occur on the request path |
| startup synthesis warmup, then first user request | **206 ms** | about 388 ms | `ready.warmed_up=true`; first user request reuses warmed graph arenas |
| second request without restart | 213 ms | about 422 ms | confirms persistent-worker steady state |

The warmup itself is discarded and is not included in user-facing latency. The
first emitted chunk remained exactly 1,920 samples (80 ms); no amplification or
silence suppression was applied. The native PCM diagnostic reported float peak
about `0.0246` and s16 peak `805`, confirming that conversion is not the source
of the latency or amplitude behavior.

## Interpretation

The native path already meets the 0.6–0.7 s first-PCM target on this machine
when startup warmup is part of the worker lifecycle: the measured user request
was about 0.21 s. A cold request does not meet that target and must not be
compared with a warmed FasterQwen profile. The new `--warmup-synthesis` flag
therefore makes warmup state explicit in the `ready` contract.

This probe does not yet prove voice-quality parity, multi-seed stability,
long-text capacity, cancellation, or release acceptance. Those remain in the
hardware matrix and must be rerun with the merged qwentts metrics ABI and the
final pinned runtime bundle.
