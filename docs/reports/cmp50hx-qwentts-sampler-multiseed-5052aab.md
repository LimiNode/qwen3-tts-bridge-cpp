# CMP 50HX canonical stochastic sampler multi-seed gate

This report records the canonical qwentts.cpp `5052aab` replay on seeds 1000,
1002, and 1006. The machine-readable record is
[`cmp50hx-qwentts-sampler-multiseed-5052aab.json`](cmp50hx-qwentts-sampler-multiseed-5052aab.json).

## Result

| Seed | Talker trace | Common prefix | Frame 2 / Talker c0 (Philox subseq 32) | Classification |
| ---: | :---: | :---: | :---: | --- |
| 1000 | exact | 32/32 | native 1551 = Python 1551 | exact common prefix |
| 1002 | mismatch | 32/32 before boundary | native 845 ≠ Python 1042 | early Talker divergence |
| 1006 | exact | 32/32 | native 1525 = Python 1525 | exact common prefix |

The native runs materialize three frames while the Python runs materialize two;
that shape difference is recorded separately as a termination/materialization
observation and is not counted as a token mismatch in the common prefix.

## Seed 1002 actual sampler capture

Seed 1002 was replayed with bounded capture at Talker frame 2, c0, Philox
subsequence 32. Both sides use the same `u = 0.3574715555`. The native graph
and Python harness retain the same 50-token candidate set (candidate-set SHA
`a2ee7ea0c259d3afe8fcf4fbff8148745154e74bf7a2216400ca5fd0134acef9`), but
their Talker logits differ before sampling:

```text
logit cosine       0.99897301197052
max absolute diff  1.2155921459197998
mean absolute diff 0.18595653772354126
```

The actual CDF crossings explain the selected tokens:

```text
native: target=0.9203490619659424; cdf[845-1]=0.8650041818618774;
        cdf[845]=1.3105316162109375  -> selected 845
python: target=0.3574715554714203; cdf[1042-1]=0.34459060430526733;
        cdf[1042]=0.38628870248794556 -> selected 1042
```

Token 845 is below the Python target (`cdf[845]=0.32847529649734497`),
while token 1042 is above it. Conversely, the native accumulator uses its
own F32 weights and selects 845. These are actual graph/harness tensors, not a
CDF recomputation from a dumped logit vector.

## Scope

The bounded result supports this conclusion:

> The seed-1002 mismatch is a Talker model/logit numerical divergence before
> stochastic selection. Candidate membership is equal; sampler semantics are
> not implicated by this capture.

No production temperature, top-k/top-p, repetition penalty, EOS handling, or
AR/KV behavior was changed. The remaining termination difference (`3` native
frames versus `2` Python frames) is a separate gate.

The next investigation should therefore compare the Talker forward path/state
at frame 2 (and its backend arithmetic) rather than modify the sampler.
