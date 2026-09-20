# CMP 50HX predictor-state probe — seed 1008

This is a bounded follow-up to the full-history replay. Complete 16-codebook
Talker frames 0..6 were forced identically in the native and Python paths, so
the next comparison starts from the same semantic history. The run keeps the
production stochastic settings unchanged and captures frame-indexed predictor
logits for the first within-frame divergence.

## Result

The forced Talker history is exact through frames 0..6. Predictor logits remain
near-identical through frame 1, predictor step 9, then diverge materially at
the next codebook:

```text
first material divergence:
  frame              1
  predictor step     10
  logical codebook   11
  cosine             0.999845277
  max absolute error 1.14267
  mean absolute error 0.247423
```

The preceding step is still close:

```text
frame 1 / step 9:
  cosine             0.999999986
  max absolute error 0.0193539
  mean absolute error 0.00605728
```

The next step grows further (`cosine=0.997290304`, `max_abs=6.10856`,
`mean_abs=1.10876`). When the frame-1 code history is forced, frame 2 step 10
returns to near-exact agreement (`cosine=0.999999982`, `max_abs=0.0171223`,
`mean_abs=0.00336306`).

## Interpretation

This localizes the next investigation to within-frame code-predictor state or
backend numerical behavior around acoustic codebook 11. It is not evidence of
a new Talker CDF sampler defect: the complete preceding Talker history was
forced, and no production sampling parameters were changed. It is also not an
EOS result; termination parity was not tested by this bounded diagnostic run.

The result should be read as a localization gate, not as proof of a particular
KV-cache or CUDA operation. The next useful bisection is:

1. force predictor codebooks 1..10 and compare the hidden/state update before
   codebook 11;
2. compare the raw predictor logits and cache contents before and after that
   update;
3. inspect attention and numerical behavior only after the first divergent
   tensor is identified.

Production temperature, penalties, EOS handling, and sampler semantics remain
unchanged until that bisection is complete.

## Provenance

The native binary reports qwentts.cpp `54d9ece` and was captured on an NVIDIA
CMP 50HX (compute capability 7.5, 20479 MiB) with GGML CUDA. The Bridge pin in
this report is the canonical diagnostic merge `4a7f2c66`; the runtime binary
and the Python harness are fingerprinted separately in the companion JSON.

The raw capture and all compared predictor-logit tensors are committed beside
this report. Their SHA-256 values are recorded below and in the JSON evidence.

| Artifact | SHA-256 |
| --- | --- |
| `native/seed1008-max8-predictor.raw.log` | `E72155CD1D92C843ED416C8622D4F37DAB16A7897DEEB864792478654815BE38` |
| `input/forced-talker-frames.txt` | `15D73293304CD935766D5905EB8F223833FA9784418B74AC3DD1D8473F412291` |
| `native/predictor-logits-frame1-step10.bin` | `D9C2A737D8F06EF18E5829F674F61BAFFDDF5B463C66DDA0AAA39181AA05DA89` |
| `python/predictor-logits-frame1-step10.bin` | `F0209920CF6A32E8AEE4548C5526DC96B746CE488CF1E7BBD07325A3B30DA8FE` |

The remaining frame/step tensors listed in the JSON are committed in the same
directory and were used for the preceding and following-step comparisons.
