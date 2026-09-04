# CMP 50HX optimization closure

Date: 2026-09-05

This note closes the current FasterQwen optimization pass for the 1.7B Base
voice-clone path on CMP 50HX (20 GiB). A candidate is considered useful only if
it improves first PCM or sustained cadence without introducing playback
starvation, broken EOS/cancellation, or an unacceptable change in the selected
voice.

## Decision matrix

| Candidate | Result | Decision |
| --- | --- | --- |
| `max_seq_len=768`, E4, W33 | about 309-313 ms cadence, parity retained | accepted as bounded low-latency profile |
| `max_seq_len=448`, E3/E4, W29 | about 600-617 ms first PCM, starvation 0 | accepted as ultra profile |
| Prefix-KV reuse, W448 | about 521-543 ms on cache hits; identity retained in listening | accepted only as fastest experimental profile |
| W384 / smaller codec windows | a few ms faster, materially less capacity | research-only |
| Async codec decode | no repeatable latency gain; earlier assertion failure | rejected |
| Talker-only `torch.compile` | prior A/B changed codec trajectory; current compile-only run stalled in warmup | rejected |
| Decode-graph compilation | earlier A/B changed codec frame count and hash | rejected |
| Fused gate/up or Triton SiLU kernel | no end-to-end gain; Triton changed codec hash | rejected |
| Efficient SDPA / matmul precision changes | no repeatable gain | rejected |
| Precision-hook removal | changed codec/PCM trajectory | rejected |
| Static output and dropped prefill state | within run-to-run noise | diagnostic-only |

## Remaining theoretical work

The following are not configuration-level optimizations and were not promoted:

- a hand-written fused CUDA Talker kernel;
- a fully unrolled first-chunk graph combining Predictor and Talker;
- more aggressive quantization or model distillation;
- allocator/KV-cache redesign;
- the native `qwentts.cpp`/GGML backend.

These require a new runtime or model path and must be evaluated with fresh
hardware A/B measurements. The native backend is tracked separately and does
not replace the accepted Python/FasterQwen release path.

## Final conclusion

For the current Python/FasterQwen Base path, the practical optimization space
is exhausted. The largest safe gain is bounded `max_seq_len` reduction; the
largest latency gain overall is opt-in prefix-KV reuse with an explicit
perceptual-risk label. Further work should focus on production routing,
multilingual/long-text acceptance, packaging, and the native DLL backend rather
than additional tuning of the existing graph.
