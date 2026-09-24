# Clean canonical component replay — seed 1002

This is a clean-checkout replay of the component gate. The qwentts.cpp checkout was exactly `716290c666f6cff52c3cd3e238b1052218b187b5`; `git status --porcelain` was empty before the run. The committed harness files are fingerprinted in the JSON. The later qwentts PR #45 merge (`40ab5eb…`) only removes a dead graph field and does not alter this runtime path.

The replay reproduced the same first mismatch (`frame 2`, subsequence `32`, native c0 `845`, Python c0 `1042`, `u=0.3574715555`) and the same component metrics as the earlier evidence. Frame 1 codec/acoustic/pre-overlay are exact; overlay/input are near-exact at `2.98e-8` max absolute error. Frame 2 codec is exact and overlay is near-exact; acoustic/pre-overlay/input diverge only after predictor-code divergence.

This closes the previous evidence gap: the result is no longer based on an old checkout plus an uncommitted local harness patch.

The result does not prove that every native and Python numerical operation is
identical. It establishes that, under the shared history exercised here, the
investigated forward paths are near-equivalent; free-running stochastic
trajectories can still cross token-selection boundaries and then diverge.
