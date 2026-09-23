# CMP 50HX component gate — qwentts.cpp `716290c`

This report records the fresh canonical CUDA run after qwentts.cpp PR #44. The Bridge main commit was `8c11a8752687932ef0c77098748bceb29b09b9ce`, and its qwentts gitlink is exactly `716290c666f6cff52c3cd3e238b1052218b187b5`.

The run used seed `1002`, stochastic ICL, three generated frames, frozen F32 Talker/codec GGUFs, and the production sampling parameters (`temperature=0.9`, `top_k=50`, `top_p=1.0`, repetition penalty `1.05`, matching subtalker settings). No forced history or EOS disabling was used. Native binary SHA-256 is `5BE575CDFA0EA31448135D74A783665AFAE2CF70B565021EA10D373ECAB24735`.

## Result

The first Talker mismatch remains at frame 2 / Philox subsequence 32: native selected c0 `845`, Python selected c0 `1042`, with the same deterministic draw (`u≈0.3574715555`). The component readback now compares the same arithmetic contract on both sides:

```text
codec = semantic c0 embedding
acoustic = predictor codebook 1..15 embedding sum
pre_overlay = codec + acoustic
input = pre_overlay + overlay
```

| frame | component | result |
|---|---|---|
| 1 | codec / acoustic / pre-overlay | exact (all values) |
| 1 | overlay | cosine 1.0, max abs 2.98e-8 |
| 1 | input | cosine 1.0, max abs 2.98e-8 |
| 2 | codec | exact (all values) |
| 2 | acoustic | cosine 0.898462951183, max abs 0.0870437622 |
| 2 | pre-overlay | cosine 0.907892227173, max abs 0.0870437622 |
| 2 | overlay | cosine 1.0, max abs 2.98e-8 |
| 2 | input | cosine 0.936362445354, max abs 0.0870437622 |

Thus #44 fixed the diagnostic overlay readback: frame 1 codec/acoustic/pre-overlay are exact and overlay/input are near-exact at FP32 dump precision; frame 2 codec is exact and overlay remains near-exact. The frame-2 acoustic/pre-overlay/input difference follows the already observed predictor-code divergence; it is not evidence of a new overlay arithmetic or graph defect. The raw native log is stored next to this report.

The Python side was an isolated `debug-clone-cossim.py` harness with a recorded component hook. Its modified-file hashes are recorded in the JSON; the base checkout is identified as qwentts.cpp `1ebed080b88b8202a910d9d7753faccc8de9f59d`. This is research evidence, not a claim that the harness working tree was clean.
