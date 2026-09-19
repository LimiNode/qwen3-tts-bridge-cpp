# CMP 50HX long-horizon AR/KV probe — seed 1008

This is the next bounded gate after the six-frame same-conditioning sampler
matrix. Seed 1008 was selected because its Talker trace and frame-2 predictor
sampler gate were exact through the previous run. The run extends
`max_new_tokens` from 6 to 16 without changing sampling parameters or native
runtime behavior.

## Result

The native run produced 16 frames. The Python harness remained exact through
semantic frames 0–6, then reported the first mismatch at frame 7:

```text
Philox subsequence = 112
u                  = 0.4909121990
native Talker      = 864
Python Talker      = 980
```

The Python harness stopped after reporting that mismatch (15 frames were
materialized on its side). The complete raw trace is preserved alongside the
native semantic-code dumps in the report artifact directory.

This is a different boundary from the earlier seed-1006 frame-2 predictor
near-tie. The frame-2 predictor sampler gate remains positive for seed 1008
(selected token 832 and equal candidate membership), but this run did not
capture actual predictor intermediates for frame 7.

## Interpretation

The first long-horizon mismatch is now localized to accumulated Talker
autoregressive state or numerical drift by frame 7. It is not evidence of a
new sampler graph defect, and it is not an EOS/termination result. Production
sampling, EOS policy, and AR/KV implementation were not changed.

The next diagnostic should compare, at frame 7 / subsequence 112:

1. Talker logits before sampling;
2. top-k candidate membership and probabilities;
3. the actual Python selection accumulator and native graph intermediates;
4. the Talker/KV state immediately before that frame.

That bisection must preserve the same frozen conditioning and Philox draw. Do
not tune temperature, EOS penalties, or production sampling based on this
single long-horizon boundary.

## Provenance

The binary reports qwentts.cpp `54251f3` and was run on the CMP 50HX CUDA
backend (compute capability 7.5, 20479 MiB) with PyTorch `2.8.0+cu128` on the
Python side. Full SHA-256 and request metadata are in the companion JSON.
