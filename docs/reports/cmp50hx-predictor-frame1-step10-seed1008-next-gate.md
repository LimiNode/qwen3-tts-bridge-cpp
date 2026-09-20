# Next gate: predictor-prefix parity before frame 1 / codebook 11

The first material divergence in the seed-1008 evidence is reported at frame
1, predictor step 10 (logical acoustic codebook 11). The next run must first
make the predictor prefix an explicit invariant; otherwise a hidden-state
mismatch could simply be the consequence of a different earlier code token.

## Required setup

1. Keep the same frozen conditioning, seed, sampling parameters, and complete
   Talker history used by the existing evidence.
2. Assert that every preceding predictor input token is identical on both
   implementations.
3. Force predictor codebooks 1..10 to the same values on both sides before
   comparing the step-10 state. The forced values and their source hash must
   be recorded as a sidecar, just like the Talker frame sidecar.
4. Verify that native and Python predictor input embeddings are identical for
   each forced prefix step.

## Measurements

Capture native and Python post-RMSNorm hidden states immediately before the
`lm_head` at frame 1 steps 9, 10, and 11. Also capture the corresponding
logits and record tensor shape, dtype, finite-value status, and SHA-256.

The diagnostic decision boundary is:

```text
same hidden, same logits       -> predictor prefix parity
same hidden, different logits   -> lm_head / matmul path
different hidden                -> divergence before lm_head
```

When hidden states differ, this is not by itself proof of an attention or KV
defect. The next bisection must inspect predictor-layer outputs in order and
separate input embedding, attention/KV, MLP, residual, final norm, and
post-norm state.

This gate is therefore described as **pre-lm_head versus lm_head**. It must not
be reported as a direct **KV/attention versus lm_head** result until the first
divergent predictor-layer tensor is identified.

Production sampling, penalties, EOS handling, and runtime behavior remain
unchanged throughout this diagnostic sequence.
