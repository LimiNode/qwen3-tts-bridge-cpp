# CMP 50HX actual Python sampler diagnostic — seed 1006

This report is the follow-up to the native-only boundary evidence. It runs the Python Qwen3-TTS reference harness with CUDA PyTorch on the same CMP 50HX and captures the actual `torch.multinomial` probability input and selection arithmetic at the first known divergence: frame 2, predictor step 9, logical codebook 10 (`Philox subsequence 42`).

## Provenance

- Bridge base: `843c3b75b973f973556640429212f852aed9d610`.
- qwentts.cpp canonical commit: `54251f3d666f50788866b3d575687db113ede224`.
- Runtime banner: `qwentts.cpp 54251f3 (2026-09-19)`.
- Native binary SHA-256: `1B5CBB0EEEB2CB23D9A4AD14D524D9C3173B141896A365A7A7B7B31306514F17`.
- GPU: NVIDIA CMP 50HX, compute capability 7.5, 20,479 MiB.
- Python: PyTorch `2.8.0+cu128`, CUDA `12.8`.

Raw logs and the captured Python sampler tensors are committed beside the [machine-readable JSON](cmp50hx-qwentts-python-sampler-seed1006-54251f3.json).

## Configuration

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
frame=2
predictor_step=9
logical_codebook=10
Philox subsequence=42
```

Both native and Python runs use the same F32 Talker/codec weights and exported reference latents. The native run exited successfully and generated six frames. The Python run generated five frames; that remains a separate EOS/termination discrepancy and does not change the first token-selection comparison.

## Actual Python sampler capture

The diagnostic hook runs inside the monkeypatched `torch.multinomial`, after Transformers top-k/top-p warpers. It therefore captures the actual probability tensor consumed by Python, not a reconstruction from dumped logits.

```text
u                 = 0.6810894608
selected          = 1168
candidate_count   = 50
candidate set     = actual surviving IDs after warpers
sum (F64)         = 0.9999999403953552
target = u * sum  = 0.6810894202536666
```

The captured Python candidate set differs from native by exactly one near-tied pair:

```text
Python-only: 581
Native-only: 1972
```

Python values around the selected token are:

```text
token 1168: probability=0.022467641159892082
            F32 cumsum=0.6842835545539856
            F64 selection accumulator=0.684283584356308

token 1180: probability=0.020546214655041695
            F32 cumsum=0.704829752445221
            F64 selection accumulator=0.7048297990113497
```

The harness now stores both cumulative representations explicitly:

- `sampler-cdf-f32.bin` — diagnostic `numpy.cumsum(..., dtype=float32)`;
- `sampler-selection-cdf-f64.bin` — the F64 accumulator used by the existing selection loop;
- `sampler-sum-f64.bin` and `sampler-target-f64.bin` — the exact normalization values used for selection.

The reference selection behavior was not changed. The new artifacts only expose its existing arithmetic.

## Native comparison

The actual native GGML CUDA graph readback at the same gate reports:

```text
u                 = 0.6810894608
selected          = 1180
top-k #50         = 1972, logit=23.44990921
top-k #51         = 581,  logit=23.44897461
candidate set     = adbb0dbad1d48e54
```

Native CDF intervals remain internally consistent:

```text
token 1168: 0.6539161801 → 0.6762740612
token 1180: 0.6762740612 → 0.6966853738
u:                              0.6810894608
```

Thus native selects `1180` lawfully from its own candidate set and CDF. Python selects `1168` lawfully from a different candidate set and its own selection accumulator.

## Conclusion and remaining gates

This run upgrades the earlier hypothesis to a direct cross-stack observation:

```text
actual Python candidate set ≠ native candidate set
difference = 581 ↔ 1972 at a near-tied top-k cutoff
```

It does not establish that native and Python probabilities or CDF arithmetic are identical; they are already fed different candidate sets. It also does not close long-horizon AR/KV parity or the separate EOS/termination discrepancy.

No production sampling, EOS penalty, or AR/KV behavior was changed. The next clean experiment is to repeat this same actual-tensor capture for seeds `1000`, `1002`, and `1008`, then decide whether the boundary instability is systematic before considering any runtime policy change.
