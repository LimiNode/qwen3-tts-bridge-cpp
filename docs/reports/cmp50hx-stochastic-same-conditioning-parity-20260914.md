# CMP 50HX stochastic same-conditioning parity

Status: **harness ready; hardware run pending**.

This gate follows the greedy first-frame F32 probe. It isolates stochastic
token selection before any long-horizon AR/KV claim. Both stacks must use the
same Base checkpoint, frozen `.spk`/`.rvq` conditioning, prompt, seed,
temperature, top-k, top-p, and repetition penalty.

The qwentts.cpp diagnostic (`tests/debug-clone-cossim.py --stochastic`) uses
the qwentts Philox stream in Python and passes the same parameters to the
native CLI. The run compares:

- Philox uniforms and selected Talker codebook-0 tokens for each frame;
- all 16 first-frame codebooks (`codes-full.bin`), including the 15 predictor
  selections;
- existing frozen-conditioning tensor dumps and hashes.

The gate is executable and fail-closed. A sanitized result must be accepted by
`scripts/validate-cmp50hx-stochastic-parity.py`; it must explicitly record
`stochastic_sampler_parity_closed: true` while keeping
`long_horizon_ar_kv_parity_closed: false`.

No production sampling, EOS, temperature, or RNG policy is changed by this
diagnostic. A successful first-frame result is not evidence of multi-frame
autoregressive parity; that is the next independent gate.
