# CMP 50HX qwentts first-mismatch replay — seed 1008

This report records a fresh CUDA `sm_75` replay from canonical qwentts
`5052aab22c4a237b1f14c853d2857055cd346c51`.

The run used the F32 Talker and codec GGUFs, exported reference `.spk/.rvq`
latents, stochastic sampling (`temperature=0.9`, `top_k=50`, `top_p=1.0`,
repetition penalty `1.05`), seed `1008`, and diagnostic target
`frame=1 / graph_step=9 / logical_codebook=10 / Philox subsequence=26`.

## Result

The first two frames are exact across all 16 codebooks: `32/32` values match.
The target sampler also agrees:

```text
u                 0.7944138646
native selected   1337
Python selected   1337
```

Native predictor-vs-Python diagnostics at the target are near-identical:

```text
logits  cosine 1.000000  max_abs 1.5787e-02  mean_abs 7.4808e-03
hidden  cosine 0.999999  max_abs 7.8991e-02  mean_abs 2.9562e-03
```

Native materialized three frames while Python materialized two. The strict
first-mismatch analyzer therefore rejects the rank-2 shape mismatch instead of
silently truncating arrays. This is recorded as a separate termination/
materialization difference; it is not a predictor-token mismatch.

The previously reported `1265 ↔ 1337` split is not reproduced by this canonical
run and remains historical/unreproduced evidence. No production sampler, EOS,
temperature, or top-k behavior was changed.

Machine-readable provenance and the raw log are adjacent:

- [JSON evidence](cmp50hx-qwentts-first-mismatch-seed1008-5052aab.json)
- [raw log](raw/cmp50hx-qwentts-first-mismatch-seed1008-5052aab.raw.log)
