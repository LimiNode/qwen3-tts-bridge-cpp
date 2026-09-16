# CMP 50HX multi-frame AR/KV probe

Date: 2026-09-16  
Status: failed gate / investigation required  
Evidence: [`cmp50hx-ar-kv-probe-20260916.json`](cmp50hx-ar-kv-probe-20260916.json)

This is the first probe after the four-seed stochastic same-conditioning gate passed. It deliberately uses the same F32 models, exported speaker/RVQ conditioning, Philox sampler, and qwentts.cpp merge as the positive matrix, but requests six Talker steps (`max_new_tokens=6`) for seed `1006`.

Observed output:

- The first two frames are exact, including all 16 predictor codebooks.
- Talker codebook-0 remains equal through the next observed frames (`27, 99, 1525, 220, 1206`).
- Predictor codes first diverge at frame 2, codebook 10 (`native=1180`, `Python=1168`).
- Native writes six frames; Python writes five. The current verifier aborts when its compact `[Sample]` trace (limited to the first two steps) is compared with the full Python trace, so EOS attribution is intentionally unresolved.

This does not prove whether the root cause is KV/history state, predictor conditioning after frame 1, or a termination-contract difference. It is a bounded diagnostic result. The next implementation step is to make the native diagnostic trace explicitly cover every generated frame (and predictor codebook), then compare per-frame logits/history before changing any sampler or EOS policy.
