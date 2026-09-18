# CMP 50HX qwentts.cpp full-trace probe — seed 1006

This report records the first CUDA `sm_75` run from qwentts.cpp
`304cd57efd5cd58a8dee3106f96292f707ca7617`. It is a new diagnostic artifact;
historical report #102 remains immutable.

## Run contract

- CMP 50HX, compute capability 7.5, 20,479 MiB VRAM.
- F32 Talker and codec GGUFs, frozen direct-reference/ICL conditioning.
- Stochastic seed `1006`, `max_new_tokens=6`, temperature `0.9`, top-k `50`,
  top-p `1.0`, repetition penalty `1.05`.
- No synthesis warmup (`startup_synthesis_warmup: false`).
- The binary self-reports `qwentts.cpp 304cd57`; its SHA-256 and all input
  hashes are recorded in the companion JSON.
- The run used an isolated Python diagnostic harness copy with frame-indexed
  predictor hooks. Its exact file hashes and patch hash are recorded in
  `provenance.python_harness`; the old workspace commit is preserved as run
  provenance and is not rewritten to the current Bridge `main`.

Raw combined output is preserved in
[cmp50hx-qwentts-fulltrace-seed1006-304cd57e-raw.txt](cmp50hx-qwentts-fulltrace-seed1006-304cd57e-raw.txt).

## Observed parity

- Talker Philox trace: `6/6` frame-start draws exact.
- Reference RVQ: `3440/3440` values exact.
- Predictor logits and argmax remain effectively identical through frames 0–1.
- Frame 2 predictor steps 0–9 still have cosine approximately `1.0` and the
  same argmax. The first selected-token mismatch is logical codebook 10
  (predictor step 9): native selects `1180`, Python selects `1168`, with the
  same Philox uniform `u=0.6810894608`.
- At that step the logits differ only by F32-scale noise (`max |error|`
  `0.013336`, cosine `1.0`), yet stochastic selection returns different
  tokens. The exact mechanism is still open: top-k membership, probability/CDF
  rounding, and backend accumulation must be distinguished with native graph
  intermediates. This is the first causal gate, not a post-hoc long-horizon
  state failure.
- Once codebook 10 differs, frame 2 predictor step 10 and later show the
  expected state drift (for example cosine `0.99852`, max error `3.695`).
- Native emitted 6 frames while Python emitted 5. This EOS/termination mismatch
  is recorded separately and does not explain the already observed frame-2
  token mismatch.

## Interpretation and next gate

The bounded CUDA diagnostic path is now proven to dump frame-indexed predictor
logits on the real CMP 50HX. The remaining parity issue is narrower than the
historical wording suggested: same-conditioning model outputs are numerically
close before the first mismatch, but top-k/CDF sampling is sensitive to those
small differences. This is near-equal F32 parity, not bit-exact logits. Do not
change production sampling or EOS policy from this single run.

Next experiment: replay the frame-2 predictor step and dump the actual native
graph tensors after top-k mask/scatter, softmax, and cumsum, alongside Python
candidate sets, logits, cumulative probabilities, and the same `u`. Preserve
the kth and k+1th logits, candidate-set hashes, and CDF values around tokens
`1168` and `1180`. Only after that should the four-seed matrix
(`1000/1002/1006/1008`) be repeated.
