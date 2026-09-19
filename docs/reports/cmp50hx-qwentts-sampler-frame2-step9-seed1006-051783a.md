# CMP 50HX qwentts sampler diagnostic — seed 1006

This report records the corrected CUDA diagnostic run after qwentts.cpp PR #19. It targets the first observed stochastic predictor mismatch: frame 2, predictor step 9, logical codebook 10.

## Provenance

- Bridge base: `81dced64419de66cfa5cf3069b23f5f781bfe70c`.
- qwentts.cpp canonical merge: `051783a167b7c1d46e4bec8db13a24435247623c`.
- Runtime banner: `qwentts.cpp 051783a (2026-09-19)`.
- Native binary SHA-256: `E621A2728707CAE808A9B3043CFE4C960C032C14B73E3163E10751AB9EC47E6C`.
- GPU: NVIDIA CMP 50HX, compute capability 7.5, 20,479 MiB, GGML CUDA.
- Raw log: [`cmp50hx-qwentts-sampler-frame2-step9-seed1006-051783a.raw.log`](cmp50hx-qwentts-sampler-frame2-step9-seed1006-051783a.raw.log), SHA-256 `0A0907E3257C016741B1337B8D246F40DA14910511E256E44919F70BE55FD0A7`.

The model and reference-latent hashes, Python harness fingerprints, and all machine-readable values are in the companion [JSON evidence](cmp50hx-qwentts-sampler-frame2-step9-seed1006-051783a.json).

## Run configuration

The native run used exported reference latents and the shared stochastic settings:

```text
seed=1006
max_new_tokens=6
temperature=0.9
top_k=50
top_p=1.0
repetition_penalty=1.05
subtalker_temperature=0.9
subtalker_top_k=50
subtalker_top_p=1.0
```

The run exited successfully, generated six frames, and produced first-frame codes in 2,045.5 ms. These timings are diagnostic-run measurements, not a production latency acceptance result.

## Native actual graph readback

The retained GGML CUDA graph tensors at frame 2 / predictor step 9 report:

```text
vocab=2048                 top_k=50
Philox u=0.6810894608      selected=1180
kth:       id=1972  logit=23.44990921
k+1:       id=581   logit=23.44897461
candidate_set_hash=adbb0dbad1d48e54
masked_logits_hash=2d74f1ba87080ba
probabilities_hash=17fbbc3349ef185f
cdf_hash=44904d516b53ab2f
```

Both tokens involved in the cross-stack selection are in the native top-50. Their native CDF intervals are:

```text
token 1168: [0.6539161801, 0.6762740612]
token 1180: [0.6762740612, 0.6966853738]
u=0.6810894608
```

The complete native top-k ID list and per-token values are machine-readable in the JSON artifact. The hashes are from tensors read back from the native diagnostic graph, not from a host-side recomputation.

## Python comparison boundary

The available Python logits were captured in the earlier same-conditioning run. Because this workstation has CPU-only PyTorch (`torch 2.8.0+cpu`, no CUDA), Python sampler intermediates could not be rerun on the CMP 50HX. The values below are therefore an offline host reconstruction from the captured Python predictor logits, not actual Python graph readbacks.

```text
Python top-k boundary: 581 (kth) vs 1972 (k+1)
Python candidate_set_hash=15346a26c6cf9f0e
Python selected=1168
```

The native and reconstructed Python candidate sets differ by exactly the near-tied boundary pair:

```text
native-only: 1972
python-only: 581
```

This is strong evidence that the first observed divergence is consistent with top-k candidate-membership instability caused by a very small logit difference at the cutoff. It is not, by itself, proof that native and Python softmax/cumsum implementations are numerically identical or that no backend-specific selection effect remains.

## Scope and next gate

What this run establishes:

- the corrected qwentts diagnostic storage is live on the CMP 50HX CUDA backend;
- native actual graph readback reaches the expected frame 2 / step 9 gate;
- the first mismatch is localized to stochastic selection inputs whose top-k membership differs at a near tie (`581` versus `1972`).

What remains open:

- actual Python graph tensors for the same step;
- backend softmax and cumulative-sum numerical comparison;
- long-horizon AR/KV parity after the first token divergence;
- the separate EOS/termination difference observed in the earlier six-versus-five-frame comparison.

Do not change production sampling, EOS penalties, or AR/KV behavior based on this report alone. The next experiment should capture the same top-k, masked-logit, probability, and CDF tensors on a CUDA-capable Python environment, then repeat the diagnostic for seeds `1000`, `1002`, and `1008`.
