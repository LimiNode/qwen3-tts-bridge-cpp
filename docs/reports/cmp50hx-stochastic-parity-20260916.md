# CMP 50HX stochastic same-conditioning parity

Date: 2026-09-16  
Status: passed  
Evidence: [`cmp50hx-stochastic-parity-20260916.json`](cmp50hx-stochastic-parity-20260916.json)

## Scope

This run is the next gate after the greedy first-frame experiment. Python/FasterQwen and native qwentts.cpp used the same exported speaker embedding, RVQ reference latents, transcript, text, language, F32 GGUF weights, sampling parameters, and Philox seed. Native and Python were compared for two generated Talker steps (`max_new_tokens=2`), including the 16 predictor codebooks of the first frame.

The qwentts.cpp runtime is pinned to canonical merge `a0071cb6e8fb4c6f48a1d02929ddf2c2da460abd` (PR #14). The binary was built from the same tree (`c98602e29aec865949d12aa97d4d48acc8dc343e`) before the merge commit was created.

## Result

| Seed | Philox draws | First-frame predictor codes | CodesFull | Exit |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 2/2 exact | 16/16 exact | 100% | 0 |
| 1002 | 2/2 exact | 16/16 exact | 100% | 0 |
| 1006 | 2/2 exact | 16/16 exact | 100% | 0 |
| 1008 | 2/2 exact | 16/16 exact | 100% | 0 |

The first-frame predictor code vectors are retained in the JSON so the result is independently machine-readable rather than a prose-only claim. Frozen-stage cosine similarity was `1.0` in every run.

## Interpretation

This closes the stochastic sampler/Philox and first-frame frozen-conditioning gate on CMP 50HX. It does not establish long-horizon autoregressive/KV-cache parity, reference-encoder parity, EOS behavior over production-length generations, or a 0.6–0.7 second performance result. The executable was a diagnostic CUDA F32 build; performance benchmarking remains a separate Release-build task.

The next parity gate is multi-frame AR/KV replay under the same conditioning. Production sampling or EOS policy should not be changed based on this result alone.
