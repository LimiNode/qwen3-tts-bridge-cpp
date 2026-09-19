# CMP 50HX stochastic sampler multi-seed gate

This report repeats the bounded stochastic sampler comparison after qwentts.cpp
PR #21 (`54251f3d666f50788866b3d575687db113ede224`). It uses the same frozen
conditioning, CUDA models, reference latents, sampling parameters, and Philox
schedule as the earlier seed-1006 diagnostic. The machine-readable record is
[`cmp50hx-qwentts-sampler-multiseed-54251f3.json`](cmp50hx-qwentts-sampler-multiseed-54251f3.json).

## Result

| Seed | Comparable gate | Talker trace | Frame 2 / predictor step 9 | Candidate set | Interpretation |
| ---: | :---: | :---: | :---: | :---: | --- |
| 1000 | yes | exact | native 902 = Python 902 | equal | positive same-conditioning sampler gate |
| 1002 | no | mismatch at Talker subseq 32 (`845` vs `1042`) | native 1399 vs Python 1528 | not comparable | exclude from predictor sampler pooling |
| 1008 | yes | exact | native 832 = Python 832 | equal | positive same-conditioning sampler gate |

The comparable predictor gate therefore passes **2/2** for seeds 1000 and
1008. Seed 1002 is intentionally not counted as a predictor result: its first
token mismatch occurs before the predictor frame-2 gate, so its later tensors
do not have the same model history.

The previously observed seed-1006 run remains the near-tied boundary case:
Python-only candidate `581`, native-only candidate `1972`. It is referenced by
the earlier evidence report rather than duplicated here.

## Fixed gate and arithmetic

All runs use:

```text
max_new_tokens        = 6
temperature            = 0.9
top_k                  = 50
top_p                  = 1.0
repetition_penalty     = 1.05
subtalker_temperature  = 0.9
subtalker_top_k        = 50
subtalker_top_p        = 1.0
frame                  = 2
predictor step         = 9
logical codebook       = 10
Philox subsequence     = 42
vocabulary             = 2048
```

The Python artifact directory retains both arithmetic views required for the
boundary investigation:

* `sampler-cdf-f32.bin` is a separate `numpy.cumsum(..., dtype=float32)`
  diagnostic reconstruction;
* `sampler-selection-cdf-f64.bin`, `sampler-sum-f64.bin`, and
  `sampler-target-f64.bin` record the F64 Python accumulation and its actual
  `target = u * sum` selection path.

No production sampling, EOS penalty, or AR/KV behavior was changed for this
experiment.

## Provenance and artifacts

The native binary reports qwentts.cpp `54251f3`; its SHA-256 and the Bridge
base commit are recorded in the JSON. Native raw logs, Python raw logs, and the
bounded frame-2 sampler tensors are kept under:

```text
docs/reports/cmp50hx-qwentts-sampler-multiseed-54251f3/
```

Each seed directory contains native `top-k`, masked-logit, probability, CDF,
uniform, and selected-token dumps plus the corresponding Python sampler
artifacts. The Python artifacts are actual CUDA sampler inputs captured by the
patched harness, not an offline reconstruction of native logits.

## Scope of the conclusion

This run supports the following bounded statement:

> With exact Talker conditioning, qwentts.cpp and the Python sampler selected
> the same predictor token and retained the same top-k candidate set at the
> tested gate for seeds 1000 and 1008.

It does **not** prove long-horizon AR/KV parity, EOS/termination parity, or
global numerical equality of softmax/CDF accumulation. Those remain separate
gates. The next experiment should localize long-horizon state only after these
same-conditioning sampler gates, without changing production sampling.
