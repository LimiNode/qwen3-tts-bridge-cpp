# FasterQwen runtime research

## Source history

Early candidates were reproducible local shadows over a fingerprinted source.
That was useful for falsifying hypotheses but unsuitable for release. PR #58
introduced the `external/python/faster-qwen3-tts` submodule at
`fb098012fee40511480d6c2d693f857764aae31e` and kept the codec input contract
fail-closed.

Production consolidation #63 later replaced that research revision. Final
automatic-router acceptance #66 pinned FasterQwen commit
`90b596d2ffa41eb2da173db92e6f896df11b19cb` and Qwen streaming commit
`25cc5886a753035ac3ed9d4000440b2e842e5e56`.

## Optimization decisions

| Candidate | Result | Decision |
| --- | --- | --- |
| Frozen FP32 carrier/islands | Prevented known FP16 overflow and retained finite EOS | Adopted correctness boundary |
| Right-padded codec + manual graph | Passed PCM gates and reduced codec overhead | Adopted |
| Narrower static Talker capacity | Repeatable first-PCM/cadence improvement | Adopted as profiles |
| E4/W33 | First PCM near 678 ms, cadence near 309-313 ms, starvation 0 | Adopted bounded profile |
| E3/E4/W29/W448 | Persistent first PCM median 610.901 ms, starvation 0 | Adopted ultra profile |
| Voice prefix-KV | Cached first PCM near 524 ms; audible difference minor in user review | Adopted opt-in fastest profile |
| TF32, fused gate/up, Triton SiLU, efficient SDPA | No sufficient end-to-end gain or changed trajectory/hash | Rejected as default policy |
| Async codec overlap | No repeatable latency win; earlier synchronization/assertion risk | Rejected |
| Predictor MLP Inductor | Nested CUDA Graph capture failure | Rejected |

The current Python/FasterQwen optimization pass is closed. Further large gains
require a new kernel/model/runtime path and separate quality acceptance.

See [E4 throughput](../cmp50hx-e4-throughput-research.md),
[latency batch](../cmp50hx-latency-batch-research.md), and
[optimization closure](../cmp50hx-optimization-closure.md) for individual
candidate measurements.
