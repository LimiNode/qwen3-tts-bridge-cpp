# CMP 50HX Talker input probe — seed 1002

This report is the canonical f128fe5 replay for the seed-1002 stochastic
mismatch. The machine-readable record is
[`cmp50hx-qwentts-talker-input-seed1002-f128fe5.json`](cmp50hx-qwentts-talker-input-seed1002-f128fe5.json).

## Result

The native and Python runs share `32/32` exact code values before Talker frame
2. At frame 2 / c0 they use the same Philox draw (`u = 0.3574715555`) but
select native `845` and Python `1042`.

The new input dump moves the boundary earlier than the previous layer probe:

| frame | tensor | cosine | max absolute error | interpretation |
| ---: | --- | ---: | ---: | --- |
| 1 | Talker input | 0.9999999999999994 | 5.96e-8 | effectively exact |
| 1 | L0 output | 0.9999999495 | 5.46e-4 | effectively exact |
| 2 | Talker input | 0.9363623562 | 0.08704 | first observed material divergence |
| 2 | L0 output | 0.9700533570 | 0.30302 | downstream drift |

The frame-2 input is the actual post-codebook-gather plus overlay tensor fed
to the Talker decode graph. Thus the next bisection target is the composition
of the previous frame's code-predictor outputs, codebook embeddings, overlay,
and carried decode state—not the stochastic CDF implementation.

## Scope

This evidence does not prove the exact subcomponent of the composition yet, and
it does not resolve the separate native-three-frames versus Python-two-frames
termination difference. It does establish that changing production sampling,
EOS, or AR/KV behavior is premature. The next probe should dump the individual
codebook-sum and overlay components before their final addition.
