# CMP 50HX Talker layer probe — seed 1002

This report records a clean CUDA `sm_75` replay for the first reproducible
stochastic mismatch from the canonical multi-seed gate. The machine-readable
record is [`cmp50hx-qwentts-talker-layers-e46d24f.json`](cmp50hx-qwentts-talker-layers-e46d24f.json).

## Result

The run uses the same F32 Talker/codec weights, direct latent ICL conditioning,
Philox seed `1002`, and sampler settings as the preceding seed-1002 evidence.
The common prefix is exact for `32/32` code values. At Talker frame 2 / c0,
the same Philox draw is used (`u = 0.3574715555`), but native selects `845`
and Python selects `1042`.

The layer taps show where the forward trajectories separate:

| frame | tap | cosine | max absolute error | interpretation |
| ---: | ---: | ---: | ---: | --- |
| 1 | L0 | 0.9999999495 | 0.0005456 | near exact |
| 1 | L27 | 0.9999999173 | 0.01630 | near exact |
| 2 | L0 | 0.9700533570 | 0.30302 | first observed material divergence |
| 2 | L7 | 0.9829597707 | 0.54015 | drift continues |
| 2 | L14 | 0.9888679356 | 0.84972 | drift continues |
| 2 | L21 | 0.9973682774 | 2.11848 | drift continues |
| 2 | L27 | 0.9978023263 | 4.25900 | large absolute drift |

L0 is the earliest recorded post-layer tensor. The probe does not instrument
the frame input before layer 0, so the exact pre-layer operation remains the
next bisection target.

## Scope and conclusion

This run does not implicate top-k, CDF ordering, or Philox selection semantics:
the first material difference is already present in the Talker forward path
before the sampler chooses c0. The sampler can amplify that difference into a
different token, but changing production sampling, EOS, or AR/KV behavior is
not justified by this evidence.

The native run materializes three frames while Python materializes two. That
termination/materialization difference is recorded separately and is not
counted as a token mismatch in the `32/32` common prefix.

The next diagnostic should capture the frame-2 input embedding/state immediately
before L0, then bisect the first Talker operation that diverges. A clean build
with a regenerated runtime banner should also replace the reused-build banner
noted in the JSON provenance.
