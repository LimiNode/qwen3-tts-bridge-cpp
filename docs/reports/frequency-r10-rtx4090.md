# Frequency R10 on RTX 4090

## Scope and status

This report records the final measured internal opt-in configuration for the
frequency exact-allowlist experiment. It is **not** the project default and it
is not a compatibility or latency claim for other GPUs.

The measured machine reported an NVIDIA GeForce RTX 4090 with 48 GiB of VRAM.
The profile pins its Python, Torch/CUDA, Triton installed-file manifest,
FasterQwen source/module bundle, worker bundle, model directory, and benchmark
evidence. The full contract is
[frequency-r10-internal-opt-in-candidate.md](../frequency-r10-internal-opt-in-candidate.md).

| Runtime decision | Internal R10 behaviour |
| --- | --- |
| Exact compiled prefill lengths | `18, 19, 20, 26, 27, 29` |
| All other lengths | Eager, with no implicit compilation |
| Compiled chunk schedule | `8, 8, 12` |
| Eager chunk schedule | `8` |
| Attention/correctness gate | Strict BF16 SDPA with an exact zero-delta gate |
| Default project profile | Unchanged |

An RTX 3090, a conventional 24 GiB RTX 4090, CMP 50HX, or another capable CUDA
GPU can run the generic eager worker if its model/runtime requirements are
met. None inherits this compiled profile until it has its own measured profile,
smoke, and soak evidence.

## Results

The frozen 500-record discovery holdout was measured descriptively after the
allowlist was chosen; it was not used to tune it.

| Metric | Result | Interpretation |
| --- | ---: | --- |
| Compiled coverage | 99 / 500 (19.8%) | Exact lengths only; the rest deliberately remain eager. |
| Mean first audio | 368.7 ms | Whole frozen holdout, compiled and eager combined. |
| P95 first audio | 428.3 ms | Whole frozen holdout, not an arbitrary-text SLA. |
| Inverse real-time factor | 2.689 | Equivalent to RTF about 0.372 for this holdout. |
| Compiled first-audio observation | about 237.8 ms | Narrow exact-shape path, not a global claim. |
| Operational mixed-soak median / p95 first audio | 384.5 / 1073.9 ms | Mixed traffic includes eager shapes and cancellation scenarios. |
| Operational mixed-soak maximum | 1197.2 ms | Reinforces the eager-tail caveat. |

The 504-operation Python soak completed 396 requests and cancelled 108 across
all cancellation phases. The public C++ API soak completed 225 of 250 requests
and cancelled 25. Both observed six compiled cache entries. A post-sealing
smoke then passed 36 completed and 27 cancelled requests across all compiled
lengths, eager holdouts, and cancellation phases with zero allocated CUDA
memory growth. Exact commands and sanitized evidence are retained in the
[R10 evidence README](../benchmark-artifacts/rtx4090-2026-08-01/frequency-exact-allowlist-operational-r10/README.md).

## What the numbers mean

The safe improvement is real for the six exact compiled forms, while most
natural discovery text still takes the eager route. The reported holdout p95 is
therefore a description of this corpus and machine, rather than a promise that
any input will begin speaking within 428.3 ms. In the operational soak, eager
holdouts reached roughly 1.17--1.18 s p95 first audio.

## External comparison

The upstream [Qwen3-TTS-streaming](https://github.com/NewYaroslav/Qwen3-TTS-streaming)
README reports its own RTX 5090 benchmarks, including a 208 ms aggressive
first-chunk result for `5 -> 12` and a 382 ms optimized first-chunk result for
its stable path. Our approximately 237.8 ms exact-shape observation is close
to the former in magnitude, while our whole-holdout RTF of about 0.372 is close
to the upstream reported 0.36 optimized RTF.

This is **not a strict A/B comparison**: the public upstream table does not
fully specify an identical GPU, checkpoint, request distribution, sample count,
or measurement procedure. It must not be presented as a win or loss against
that project. It is included only as context for the scale of the result.

## Next experiments

The next meaningful improvements are not more arbitrary exact lengths. They
are: reducing eager prefill cost, investigating incremental codec decoding,
overlapping autoregressive and codec work when correctness permits, and an
adaptive scheduler backed by fresh end-to-end measurements. Each needs a new
correctness contract and a holdout that remains untouched during tuning.
