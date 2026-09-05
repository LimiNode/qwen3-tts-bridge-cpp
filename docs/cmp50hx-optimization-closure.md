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

## Fresh fused-MLP confirmation

On 2026-09-05 the fused gate/up path was repeated on the CMP 50HX using the
packaged CUDA runtime (`torch 2.10.0+cu128`), FP16, registered Base voice,
`max_seq_len=448`, E3→E4 schedule, W29, and the same short Russian request.
The control and fused runs both completed with natural EOS and no worker error.

| Run | First PCM | Total synthesis | Audio duration | Local RTF |
| --- | ---: | ---: | ---: | ---: |
| control | 1230.447 ms | 12817.424 ms | 3493.125 ms | 3.669 |
| fused gate/up | 1234.415 ms | 12931.724 ms | 3573.125 ms | 3.619 |

The generated output lengths differed by one late sampling outcome (expected
for the non-fixed-seed CLI request), so the small total-time delta is not a
throughput signal. First PCM was 4 ms slower with fusion. The experiment also
confirmed that the extra fused projection does not remove the dominant
Predictor/Talker and codec costs. No production change is justified.

The packaged runtime has Triton available, but neither `torchao` nor
`bitsandbytes`; therefore an off-the-shelf int8/int4 quantization A/B cannot be
run in the sealed environment without adding a new dependency. Such a test is
tracked as a separate backend experiment rather than silently changing the
release runtime.

## Predictor-MLP Inductor prototype

As a final kernel-level attempt, an opt-in prototype compiled all five small
Predictor MLP modules with Inductor `max-autotune` before the existing graph
capture. Model loading and compilation completed, but the first PredictorGraph
capture failed with:

```text
RuntimeError: Cannot prepare for replay during capturing stage.
```

Inductor enabled its own CUDA Graph Trees for the compiled MLP callables, which
cannot be replayed while FasterQwen is capturing the enclosing graph. Disabling
the nested trees would require a separate compiler configuration and a new
capture-safe kernel path. No latency or quality measurement was possible, so
this prototype is rejected for the current runtime.

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
