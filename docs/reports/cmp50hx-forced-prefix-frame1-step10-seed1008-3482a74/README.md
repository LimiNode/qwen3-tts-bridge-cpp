# CMP 50HX forced-prefix predictor replay (seed 1008)

This diagnostic replay isolates the previously observed frame 1 / logical
codebook 11 boundary. Both implementations used the same frozen reference
latents, Talker c0 history (`1755, 1902`), Philox seed, and sampling settings.
Predictor codebooks 1..15 were forced for frames 0 and 1; in particular,
codebooks 1..10 of frame 1 were identical before the step-10 comparison.

The replay uses qwentts.cpp `3482a74` for the native binary. The Bridge main
workspace at capture time was `ceec8a4523e4a747d52732e511d4c9f4500e4306`,
pinning qwentts `590c2a2f`; the canonical qwentts EOS-harness merge is
`3fe602f240534dcda6745360cfee602cfa1f634a`. The native executable and the
Python harness are fingerprinted in `evidence.json`; the raw capture and all
compared tensors are committed beside this report.

## Result

| frame 1 predictor step | hidden cosine | hidden max abs | logits cosine | logits max abs |
| ---: | ---: | ---: | ---: | ---: |
| 9 | 0.999999106 | 0.0516806 | 1.000000000 | 0.0193539 |
| 10 | 0.999999404 | 0.0368080 | 0.999999821 | 0.0146294 |
| 11 | 0.999999642 | 0.0468922 | 1.000000119 | 0.0100574 |

All hidden tensors have shape `(1024,)`, all logits have shape `(2048,)`, and
all values are finite. The forced prefix tokens for frame 1 codebooks 1..10
are:

```text
781, 199, 990, 1501, 773, 274, 1472, 1169, 1015, 1337
```

With that prefix fixed, the former step-10 divergence is not reproduced. This
supports the narrower conclusion that the earlier mismatch was dependent on
different predictor history. It does **not** prove exact long-horizon AR/KV
parity and does not identify a KV/attention defect. The correct boundary is
`pre-lm_head vs lm_head`; layerwise predictor bisection remains the fallback
only if a mismatch survives an identical prefix.

The native run generated three frames while the Python generator returned two;
the comparison is intentionally limited to the two materialized common
frames. EOS/termination remains a separate diagnostic question.

## Reproduction contract

The harness-only `--disable-eos` option uses positive out-of-vocabulary EOS id
`65535` so Transformers retains the requested diagnostic frames. It does not
change production EOS or sampling behavior.

The complete raw capture is
`native/seed1008-forced-prefix.raw.log` (SHA-256
`d5591b1a18f24e2da08236b767fcd51270c1253a2e80c35df2f6e821ab9288b6`).
